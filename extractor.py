"""
extractor.py — Physics-Trans v2.0
PDF → paper.json (Google Cloud Document AI Layout Parser)

파이프라인:
  1단계: Document AI Layout Parser로 PDF 분석 (블록/타입/bbox)
  2단계: 블록 후처리 (하이픈 복원, 중복 제거, 헤더/푸터 제거 등)
  3단계: FIGURE 블록 bbox로 PNG 추출 (PyMuPDF)

인증: gcloud ADC (GOOGLE_APPLICATION_CREDENTIALS)
"""

import json
import os
import re
import sys

import fitz  # PyMuPDF (그림 crop 전용)
from google.api_core.client_options import ClientOptions
from google.cloud import documentai


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------

def extract(pdf_path: str, config: dict | None = None) -> dict:
    """
    PDF를 Document AI로 파싱하여 paper.json 형태의 dict를 반환한다.

    반환 구조:
      {
        "metadata": { "title", "authors", "pages", "source_pdf" },
        "blocks":   [ { "id", "type", "text", "page", "bbox" } ],
        "figures":  [ { "index", "path", "page", "bbox" } ]
      }
    """
    if config is None:
        config = {}

    output_dir   = config.get("output_dir", "output")
    figures_dir  = config.get("figures_dir", os.path.join(output_dir, "figures"))
    project_id   = config.get("project_id", "")
    location     = config.get("docai_location", "us")
    processor_id = config.get("docai_processor_id", "")

    os.makedirs(figures_dir, exist_ok=True)

    if not project_id or not processor_id:
        raise ValueError(
            "config에 project_id와 docai_processor_id가 필요합니다. "
            "config.yaml을 확인하세요."
        )

    # ── 1단계: Document AI 호출 ──────────────────────────────────────────
    dai_document = _call_documentai(pdf_path, project_id, location, processor_id)
    # Layout Parser는 document.pages가 비어 있으므로 PyMuPDF로 페이지 수 획득
    with fitz.open(pdf_path) as _tmp:
        total_pages = _tmp.page_count

    # ── 2단계: 블록 변환 + 후처리 ────────────────────────────────────────
    raw_blocks = _parse_blocks(dai_document)
    blocks     = _postprocess(raw_blocks, pdf_path)

    # ── 3단계: 그림 PNG 추출 ──────────────────────────────────────────────
    figures, yolo_fig_bboxes = _extract_figures(
        pdf_path, dai_document, blocks, figures_dir, config
    )

    # ── 4단계: 그림 내부 텍스트 블록 제거 ────────────────────────────────
    # _extract_figures에서 반환한 YOLO bbox를 이용해 그림 내부 텍스트를 본문에서 제거
    blocks = _filter_figure_text_blocks(blocks, yolo_fig_bboxes, pdf_path)

    # figure_caption 블록에 figure_path / figure_index 연결
    # _extract_figures()와 동일하게 그림 번호 순 정렬 후 매칭
    def _fig_num(cap):
        m = re.search(r"(\d+)", cap.get("text", ""))
        return int(m.group(1)) if m else 9999
    fig_captions = sorted(
        [b for b in blocks if b["type"] == "figure_caption"],
        key=_fig_num,
    )
    for cap, fig in zip(fig_captions, figures):
        cap["figure_index"] = fig["index"]
        cap["figure_path"]  = fig["path"]

    metadata = _build_metadata(blocks, pdf_path, total_pages)
    metadata["layout"] = _detect_layout(pdf_path)

    return {
        "metadata": metadata,
        "blocks":   blocks,
        "figures":  figures,
    }


# ---------------------------------------------------------------------------
# 1단계: Document AI 호출
# ---------------------------------------------------------------------------

def _call_documentai(
    pdf_path: str,
    project_id: str,
    location: str,
    processor_id: str,
) -> documentai.Document:
    """Document AI Layout Parser에 PDF를 전송하고 Document 객체를 반환한다."""
    # 한국어 Windows에서 gcloud가 CP949로 출력해 UnicodeDecodeError가 발생할 수 있음.
    # get_project_id()를 패치해 실패 시 config의 project_id를 반환하도록 처리.
    import google.auth._cloud_sdk as _cs
    _orig_get_project_id = _cs.get_project_id
    def _safe_get_project_id():
        try:
            return _orig_get_project_id()
        except UnicodeDecodeError:
            return project_id
    _cs.get_project_id = _safe_get_project_id

    try:
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=opts)
    finally:
        _cs.get_project_id = _orig_get_project_id

    processor_name = client.processor_path(project_id, location, processor_id)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    raw_document = documentai.RawDocument(
        content=pdf_bytes,
        mime_type="application/pdf",
    )
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
    )

    print(f"[extractor] Document AI 분석 중... ({os.path.basename(pdf_path)})", flush=True)
    result = client.process_document(request=request)
    doc = result.document

    # Layout Parser는 document_layout 필드를 사용 (document.pages는 비어 있음)
    dl = doc.document_layout
    top_blocks = dl.blocks if dl else []
    print(
        f"[extractor] Document AI 완료: document_layout 최상위 블록 {len(top_blocks)}개",
        flush=True,
    )
    return doc


# ---------------------------------------------------------------------------
# 2단계: 블록 변환
# ---------------------------------------------------------------------------

# document_layout text_block.type_ → 우리 block type 매핑
# Layout Parser가 반환하는 타입 문자열
_DL_TYPE_MAP = {
    "header":    "skip",   # 페이지 헤더
    "footer":    "skip",   # 페이지 푸터
    "heading-1": "section",
    "heading-2": "subsection",
    "heading-3": "subsection",
    "paragraph": "paragraph",
    "figure":    "figure",     # 그림 영역
    "table":     "table",
    "list-item": "paragraph",
    "subtitle":  "paragraph",
}


def _parse_blocks(document: documentai.Document) -> list[dict]:
    """
    Document AI document_layout.blocks (계층 트리) → 내부 블록 리스트로 변환한다.

    Layout Parser는 document.pages가 비어 있으며,
    document.document_layout.blocks에 계층 구조로 데이터를 반환한다.
    각 Block은 text_block.type_, text_block.text, text_block.blocks(하위)와
    page_span.page_start를 가진다.
    """
    blocks: list[dict] = []
    block_id_counter = [0]  # mutable container for nested function
    seen_title = [False]    # 첫 번째 heading-1 → title로 처리

    def _emit(our_type: str, text: str, page_num: int) -> None:
        """검증 후 블록 리스트에 추가한다."""
        nonlocal blocks
        text = _join_hyphenated_lines(text.splitlines())
        if not text:
            return
        if our_type == "skip":
            return
        # 첫 번째 section 블록 → title로 승격
        if our_type == "section" and not seen_title[0]:
            our_type = "title"
            seen_title[0] = True
        blocks.append({
            "id":   f"block_{block_id_counter[0]:04d}",
            "type": our_type,
            "text": text,
            "page": page_num,
            "bbox": [],   # document_layout에는 bbox 없음 (figure 추출은 PyMuPDF)
        })
        block_id_counter[0] += 1

    def _process(layout_block, inherited_page: int = 1) -> None:
        """Layout Block을 재귀적으로 처리한다."""
        tb = layout_block.text_block   # LayoutTextBlock (없으면 None)
        ps = layout_block.page_span    # LayoutPageSpan

        page_num = ps.page_start if (ps and ps.page_start) else inherited_page

        if tb is None:
            return

        dai_type = (tb.type_ or "paragraph").lower()
        text     = (tb.text or "").strip()
        children = list(tb.blocks)   # 하위 블록 (재귀)

        our_type = _DL_TYPE_MAP.get(dai_type, "paragraph")

        if our_type == "skip":
            # 헤더/푸터 중에서도 참고문헌 패턴([1], [2] 등)이면 구제
            # — DocAI가 페이지 하단 참고문헌을 footer로 오분류하는 경우 대응
            if text and re.match(r"^\[\d+\]", text.strip()):
                _emit("reference", text, page_num)
            return

        if our_type == "figure":
            # 그림 영역: 텍스트 없이 figure 블록으로 저장
            blocks.append({
                "id":   f"block_{block_id_counter[0]:04d}",
                "type": "figure",
                "text": "",
                "page": page_num,
                "bbox": [],
            })
            block_id_counter[0] += 1
            # 하위에 캡션 텍스트가 있을 수 있음 → 재귀 처리
            for child in children:
                _process(child, page_num)
            return

        if our_type == "table":
            # 표 영역: 캡션(첫 줄)과 raw text를 포함한 table 블록 생성
            if not text:
                for child in children:
                    _process(child, page_num)
                return
            lines = text.splitlines()
            caption = lines[0].strip()
            data_text = text.strip()
            blocks.append({
                "id":        f"block_{block_id_counter[0]:04d}",
                "type":      "table",
                "text":      caption,
                "data_text": data_text,
                "page":      page_num,
                "bbox":      [],
                "rows":      None,
            })
            block_id_counter[0] += 1
            return

        # section / subsection: 제목 텍스트를 먼저 출력한 뒤 하위 블록 재귀
        if our_type in ("section", "subsection"):
            if text:
                # 제목이 단독으로 있어야 하므로 하위 텍스트와 분리
                heading_text = text.split("\n")[0].strip()
                if heading_text:
                    _emit(our_type, heading_text, page_num)
            for child in children:
                _process(child, page_num)
            return

        # paragraph / table_caption 등: 하위 블록이 없으면 직접 출력
        if not children:
            if text:
                classified = _classify_paragraph(text, block_id_counter[0])
                _emit(classified, text, page_num)
            return

        # 하위 블록이 있는 paragraph: text가 하위 내용을 포함하는 경우
        # → text를 직접 출력하고 하위는 건너뜀 (중복 방지)
        if text:
            classified = _classify_paragraph(text, block_id_counter[0])
            _emit(classified, text, page_num)
        else:
            for child in children:
                _process(child, page_num)

    dl = document.document_layout
    if not dl or not dl.blocks:
        print("[extractor] 경고: document_layout이 비어 있습니다.", file=sys.stderr)
        return blocks

    for top_block in dl.blocks:
        _process(top_block)

    return blocks


def _classify_paragraph(text: str, position: int) -> str:
    """paragraph 계열 블록을 세부 타입으로 분류한다."""
    stripped = text.strip()

    # ── 필터링 ──────────────────────────────────────────────────────────
    if re.match(r"^\d{1,3}$", stripped):
        return "skip"
    if re.match(r"^\d{1,3}\.$", stripped):
        return "skip"
    if len(stripped) < 20 and re.match(r"^[a-z][a-z]{2,}[.,]?$", stripped):
        return "skip"
    if re.match(r"^arXiv:\S+", stripped, re.IGNORECASE):
        return "skip"
    if re.match(r"^PACS", stripped, re.IGNORECASE):
        return "skip"
    if re.search(
        r"Authorized licensed use limited to|IEEE Xplore|Restrictions apply\.",
        stripped, re.IGNORECASE
    ):
        return "skip"
    if re.match(r"^\d{4}-\d{4}/\d{2}/", stripped):
        return "skip"

    # 서브그림 레이블 필터: "(a)....", "(d)........" 형태
    if re.match(r"^\([a-zA-Z]\)[\s.…•·\-]{0,30}$", stripped):
        return "skip"

    # 그림 축 레이블 필터: 숫자 수열 + 한국어 단위 (예: "0 -150-100-50 0 50 100 150 웨이퍼 단면 (mm)")
    if re.match(r"^-?\d[\d\s\-\.]+\s+[가-힣]", stripped) and len(stripped) < 100:
        return "skip"

    # 전자현미경(SEM/TEM) 메타데이터 필터: "S4700 20.0kV 12.0mm x450 SE(M)" 형태
    if (len(stripped) < 80
            and not re.search(r"[가-힣]", stripped)
            and re.search(r"\d+\.?\d*\s*k[Vv]\b|\bx\d{2,5}\b|\bSE\([A-Z]+\)|\bBSE\b|\bETD\b", stripped)):
        return "skip"

    # 그림 내부 레이블 필터 (단계 1): 짧은 명사구 단편
    # (예: "Upper electrode", "RF", "Plasma", "600 kHz RF", "Si substrate")
    if len(stripped) < 80 and not re.search(r"[가-힣]", stripped):
        has_sentence = bool(re.search(
            r"\b(is|are|was|were|have|has|shows?|demonstrate|indicate|"
            r"present|report|describe|with|from|for|the)\b",
            stripped, re.IGNORECASE
        ))
        is_only_fragment = (
            len(stripped.split()) <= 8
            and not re.search(r"[.!?]$", stripped)
            and not re.match(r"^\d+\)", stripped)
            and not re.match(r"^\[?\d+\]", stripped)
            and not re.match(r"^(Fig\.|Figure|Table)", stripped, re.IGNORECASE)
        )
        if is_only_fragment and not has_sentence:
            return "skip"

    # 그림 내부 레이블 필터 (단계 2): 동사 없는 긴 기술 명사구
    # (예: "Lithography Tri-layer + Surface Spin-on material Hard mask Mandrel formation...")
    if len(stripped) < 200 and not re.search(r"[가-힣]", stripped):
        has_verb = bool(re.search(
            r"\b(is|are|was|were|have|has|had|shows?|demonstrates?|indicates?|"
            r"presents?|reports?|describes?|discusses?|analyzes?|measures?|"
            r"observes?|finds?|increases?|decreases?|achieves?|enables?|"
            r"requires?|provides?|reduces?|improves?|can|will|may|must|should|"
            r"applied|performed|used|shown|observed|measured|fabricated|etched)\b",
            stripped, re.IGNORECASE
        ))
        has_end_punct  = bool(re.search(r"[.!?]$", stripped))
        is_caption_or_ref = bool(
            re.match(r"^(Fig\.|Figure|Table)", stripped, re.IGNORECASE)
            or re.match(r"^\[?\d+\]|^\d+\)", stripped)
        )
        # 콤마 2개 이상 → 키워드 목록·저자 목록 등 보호
        has_comma_list = stripped.count(",") >= 2
        if not has_verb and not has_end_punct and not is_caption_or_ref and not has_comma_list:
            return "skip"

    # OCR 쓰레기 필터 (정상 문자 비율 < 70%)
    normal = len(re.findall(r"[\w\s.,;:!?()\[\]{}'\"/@#%&*+=<>\-]", stripped))
    if len(stripped) > 5 and normal / len(stripped) < 0.70:
        return "skip"

    # ── 캡션 ────────────────────────────────────────────────────────────
    # 실제 캡션: "Fig. N." / "Figure N." / "FIG. N." — 번호 뒤에 마침표/콜론 필요
    # 인라인 참조("Figure 1 shows...") 는 제외
    if re.match(r"^(Fig\.|Figure|FIG\.)\s*(\d+|[IVX]+)\s*[.:]", stripped, re.IGNORECASE):
        return "figure_caption"
    # TABLE N (콜론/마침표 선택적 — "TABLE 1" 단독 레이블도 포함)
    if re.match(r"^(Table|TABLE)\s+(\d+|[IVX]+)\s*(?:[.:]|$)", stripped, re.IGNORECASE):
        return "table_caption"

    # ── 참고문헌 ────────────────────────────────────────────────────────
    if re.match(r"^\[\d+\]", stripped):
        return "reference"
    # "1) Author..." / "1. Author..." 형식 참고문헌 (position > 20 : 너무 앞은 제외)
    if re.match(r"^\d{1,2}[)\.]\s*[A-Z]", stripped) and position > 20:
        return "reference"

    # ── 각주 ─────────────────────────────────────────────────────────────
    # "5 URL...", "6 Shown as...", "7 For the B band..." 형태의 각주
    if (re.match(r"^\d{1,2}\s+[A-Z]", stripped)
            and position > 5
            and len(stripped) > 20):
        return "footnote"

    # ── Abstract ────────────────────────────────────────────────────────
    if re.match(r"^abstract", stripped, re.IGNORECASE):
        return "abstract"

    # ── 수식 ────────────────────────────────────────────────────────────
    if re.search(r"\$.*?\$|\\begin\{equation\}|\\begin\{align", stripped):
        return "equation"
    math_sym = len(re.findall(
        r"[ρσπθφψωαβγδεζηικλμνξ√∑∫∂∇≈≠≤≥×÷±∞†ˆ⟨⟩ǫ]", stripped
    ))
    if math_sym >= 2 and len(stripped) < 300:
        return "equation"

    # ── 저자 ────────────────────────────────────────────────────────────
    if position < 5 and len(stripped) < 800:
        if re.match(r"^[A-Z][a-z]*\.?\s+[A-Z][a-z]", stripped):
            if "," in stripped or " and " in stripped.lower():
                return "authors"

    return "paragraph"


# ---------------------------------------------------------------------------
# 후처리
# ---------------------------------------------------------------------------

def _join_hyphenated_lines(lines: list[str]) -> str:
    """줄 목록을 하이픈 줄바꿈 규칙으로 합친다."""
    text = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if text.endswith("-") and line and line[0].islower():
            text = text[:-1] + line
        elif text:
            text = text + " " + line
        else:
            text = line
    return text.strip()


def _postprocess(blocks: list[dict], pdf_path: str = "") -> list[dict]:
    """블록 후처리: 중복 제거, 반복 헤더 제거, 저자 소속 정리."""
    blocks = _remove_duplicate_blocks(blocks)
    blocks = _remove_running_headers(blocks)
    blocks = _clean_authors_block(blocks)
    blocks = _reclassify_ref_section(blocks)
    blocks = _merge_leading_fragments(blocks)
    blocks = _relocate_orphaned_paragraphs(blocks)
    blocks = _sort_figure_captions_by_number(blocks)
    if pdf_path:
        blocks = _fix_references_fallback(blocks, pdf_path)
    return blocks


def _reclassify_ref_section(blocks: list[dict]) -> list[dict]:
    """
    'References' / '참고문헌' 섹션 헤딩 이후의 paragraph 블록을
    reference로 재분류한다. (번호 없는 참고문헌 항목 처리)
    """
    _ref_heading = re.compile(r"^(references|참고문헌|bibliography)$", re.IGNORECASE)
    in_ref_section = False
    result = []
    for b in blocks:
        if (b["type"] in ("section", "subsection", "paragraph")
                and _ref_heading.match(b.get("text", "").strip())):
            in_ref_section = True
            # 헤딩 자체는 제거
            continue
        if b["type"] == "table_caption" and in_ref_section:
            # 참고문헌 섹션 내 표 캡션 → 참고문헌 모드 해제 후 그대로 보존
            in_ref_section = False
            result.append(b)
        elif in_ref_section and b["type"] == "paragraph":
            result.append({**b, "type": "reference"})
        else:
            result.append(b)
    return result


def _merge_leading_fragments(blocks: list[dict]) -> list[dict]:
    """
    소문자로 시작하는 paragraph 단편을 직전 paragraph에 병합한다.

    DocAI가 2단 컬럼 경계에서 문장을 분리하면 다음 컬럼 첫 블록이
    소문자('and etch control.' 등)로 시작하는 단편이 된다.

    처리 방식:
    - 블록이 소문자로 시작하면, 첫 번째 문장('. ' + 대문자)까지만 단편으로 판단
    - 단편만 직전 paragraph에 병합
    - 나머지 내용(rest)은 별도 paragraph 블록으로 유지
    - figure_caption 등 비paragraph 블록을 건너뛰어 역방향 탐색
    - section/subsection 경계는 넘지 않음
    """
    result = []
    for b in blocks:
        text = b.get("text", "").strip()
        if (b["type"] == "paragraph"
                and text
                and text[0].islower()):
            # 첫 문장 경계 탐색: '. ' 뒤에 대문자
            split_m = re.search(r"\.\s+(?=[A-Z])", text)
            if split_m:
                fragment = text[: split_m.start() + 1]
                rest     = text[split_m.end() :]
            else:
                fragment = text
                rest     = ""

            target_idx = None
            for i in range(len(result) - 1, -1, -1):
                if result[i]["type"] in ("section", "subsection"):
                    break
                if result[i]["type"] == "paragraph":
                    target_idx = i
                    break

            if target_idx is not None:
                result[target_idx] = {
                    **result[target_idx],
                    "text": result[target_idx]["text"].rstrip() + " " + fragment,
                }
                if rest:
                    result.append({**b, "text": rest})
                continue
        result.append(b)
    return result


def _relocate_orphaned_paragraphs(blocks: list[dict]) -> list[dict]:
    """
    figure_caption 사이에 끼어 있는 고아 paragraph를 내용 키워드로 올바른
    subsection 뒤로 이동한다.

    판별 기준:
    - 직전·직후 블록이 모두 figure_caption인 paragraph
    - 블록 텍스트에서 subsection 제목과 겹치는 단어가 가장 많은 subsection 찾기
    - 해당 subsection의 마지막 paragraph 뒤로 이동
    """
    # ── 이동 대상 식별 ──────────────────────────────────────────────────────
    orphans: list[int] = []
    for i, b in enumerate(blocks):
        if b["type"] != "paragraph":
            continue
        prev_type = blocks[i - 1]["type"] if i > 0 else None
        next_type = blocks[i + 1]["type"] if i + 1 < len(blocks) else None
        if prev_type == "figure_caption" and next_type == "figure_caption":
            orphans.append(i)

    if not orphans:
        return blocks

    # ── 이동 ────────────────────────────────────────────────────────────────
    result = list(blocks)
    offset = 0  # 삭제 후 인덱스 보정
    for orig_idx in orphans:
        idx = orig_idx + offset
        orphan = result[idx]
        orphan_words = set(re.findall(r"[A-Za-z]{4,}", orphan["text"].lower()))

        # subsection 헤더 중 가장 많이 겹치는 것 탐색 (orphan 뒤에 있는 것만)
        best_sub_idx = None
        best_overlap = 0
        for j in range(idx + 1, len(result)):
            if result[j]["type"] == "subsection":
                sub_words = set(re.findall(r"[A-Za-z]{4,}", result[j]["text"].lower()))
                overlap = len(orphan_words & sub_words)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_sub_idx = j

        if best_sub_idx is None or best_overlap == 0:
            continue  # 매칭 없음 → 그대로

        # 해당 subsection의 마지막 paragraph 뒤 삽입 위치
        insert_after = best_sub_idx
        for j in range(best_sub_idx + 1, len(result)):
            if result[j]["type"] in ("section", "subsection"):
                break
            if result[j]["type"] == "paragraph":
                insert_after = j

        # 제거 후 삽입
        result.pop(idx)
        insert_pos = insert_after if insert_after < idx else insert_after
        result.insert(insert_pos + 1, orphan)
        offset -= 1  # 삭제로 인한 인덱스 보정

    return result


def _sort_figure_captions_by_number(blocks: list[dict]) -> list[dict]:
    """
    figure_caption 블록을 그림 번호 오름차순으로 재정렬한다.

    2단 조판 논문에서 DocAI가 캡션을 컬럼 순서로 읽어
    Fig.7이 Fig.5보다 먼저 오는 경우를 교정한다.
    각 캡션이 차지하던 위치(슬롯)는 그대로 유지하고
    내용만 번호 순으로 교체한다.
    """
    cap_indices = [i for i, b in enumerate(blocks) if b["type"] == "figure_caption"]
    if len(cap_indices) <= 1:
        return blocks

    def _fig_num(b: dict) -> int:
        m = re.search(r"(\d+)", b.get("text", ""))
        return int(m.group(1)) if m else 9999

    caps_sorted = sorted((blocks[i] for i in cap_indices), key=_fig_num)
    result = list(blocks)
    for idx, cap in zip(cap_indices, caps_sorted):
        result[idx] = cap
    return result


def _fix_references_fallback(blocks: list[dict], pdf_path: str) -> list[dict]:
    """
    DocAI가 참고문헌을 불완전하게 추출한 경우 PyMuPDF 결과로 교체한다.

    트리거 조건:
    - 번호만 있는 ref([2] 등 내용 없음)가 하나라도 존재하는 경우
    - PyMuPDF ref 수가 DocAI 완전 ref 수보다 많은 경우
    """
    all_refs = [b for b in blocks if b["type"] == "reference"]
    non_refs = [b for b in blocks if b["type"] != "reference"]

    if not all_refs:
        return blocks

    # DocAI 분석: 완전한 ref vs 번호만 있는 ref
    num_only = [b for b in all_refs if re.match(r"^\[\d+\]\s*$", b["text"].strip())]
    complete_docai = [b for b in all_refs if re.match(r"^\[\d+\].+", b["text"].strip())]

    # PyMuPDF로 내용이 있는 ref만 수집 (번호만 있는 항목은 제외)
    mupdf_refs: list[str] = []
    try:
        with fitz.open(pdf_path) as doc:
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                for mb in page.get_text("blocks"):
                    text = mb[4].strip()
                    if re.match(r"^\[\d+\]", text):
                        parts = re.split(r"(?=\[\d+\])", text)
                        for part in parts:
                            part = part.strip()
                            # 내용이 있는 ref만 수집 (번호만 있는 것은 제외)
                            if part and re.match(r"^\[\d+\].+", part):
                                mupdf_refs.append(part)
        # 중복 제거 + 번호 기준 정렬
        seen_nums: set[int] = set()
        deduped: list[str] = []
        for r in mupdf_refs:
            m = re.match(r"^\[(\d+)\]", r)
            if m:
                n = int(m.group(1))
                if n not in seen_nums:
                    seen_nums.add(n)
                    deduped.append(r)
        mupdf_refs = sorted(deduped, key=lambda r: int(re.match(r"^\[(\d+)\]", r).group(1)))
    except Exception as e:
        print(f"[extractor] 참고문헌 fallback 실패: {e}", file=sys.stderr)
        return blocks

    # 번호만 있는 ref가 있거나 PyMuPDF가 더 많으면 교체
    has_broken = bool(num_only)
    if not has_broken and len(mupdf_refs) <= len(complete_docai):
        return blocks

    if not mupdf_refs:
        return blocks

    ref_page = next((b["page"] for b in all_refs), 1)
    new_refs = [
        {
            "id": f"block_ref_{i:04d}",
            "type": "reference",
            "text": ref_text,
            "page": ref_page,
            "bbox": [],
        }
        for i, ref_text in enumerate(mupdf_refs)
    ]
    print(
        f"[extractor] 참고문헌 교체: DocAI {len(all_refs)}개(완전 {len(complete_docai)}개) → "
        f"PyMuPDF {len(mupdf_refs)}개",
        flush=True,
    )
    return non_refs + new_refs


def _remove_duplicate_blocks(blocks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for b in blocks:
        if b["type"] == "figure":
            result.append(b)
            continue
        key = b["text"][:100].strip()
        if len(b["text"]) >= 80 and key in seen:
            continue
        if len(b["text"]) >= 80:
            seen.add(key)
        result.append(b)
    return result


def _remove_running_headers(blocks: list[dict]) -> list[dict]:
    from collections import defaultdict
    text_pages: dict[str, set] = defaultdict(set)
    for b in blocks:
        if b["type"] in ("paragraph", "section", "subsection") and len(b["text"].strip()) < 120:
            text_pages[b["text"].strip()[:80]].add(b["page"])
    repeated = {k for k, pages in text_pages.items() if len(pages) >= 3}
    return [b for b in blocks if b["text"].strip()[:80] not in repeated]


def _clean_authors_block(blocks: list[dict]) -> list[dict]:
    _affil = re.compile(
        r"\b(Department|University|Institute|Laboratory|National|College|"
        r"Center|School\s+of|Faculty|Corporation|Co\.|Ltd\.|Inc\.)\b",
        re.IGNORECASE,
    )
    result = []
    for b in blocks:
        if b["type"] != "authors":
            result.append(b)
            continue
        m = _affil.search(b["text"])
        clean = b["text"][: m.start()].strip().rstrip(",").strip() if m else b["text"].strip()
        if clean:
            result.append({**b, "text": clean})
    return result


# ---------------------------------------------------------------------------
# 3단계: 그림 PNG 추출
# ---------------------------------------------------------------------------

def _collect_visual_element_bboxes(
    document: documentai.Document,
) -> dict[int, list[list[float]]]:
    """
    document.pages[].visual_elements에서 FIGURE 타입의 bbox(pt)를
    페이지 번호 → bbox 리스트로 수집한다.

    Layout Parser는 document_layout에 텍스트, pages에 visual_elements를 분리 제공.
    """
    page_bboxes: dict[int, list[list[float]]] = {}
    for page in document.pages:
        pn = page.page_number          # 1-based
        w  = page.dimension.width      # pt
        h  = page.dimension.height     # pt
        bboxes: list[list[float]] = []
        for ve in page.visual_elements:
            # type_ 은 VisualElement.DetectedLanguage 가 아닌 type_ 속성
            ve_type = getattr(ve, "type_", "") or ""
            if ve_type.upper() != "FIGURE":
                continue
            bp = ve.layout.bounding_poly if ve.layout else None
            if not bp:
                continue
            verts = bp.normalized_vertices
            if not verts:
                continue
            xs = [v.x * w for v in verts]
            ys = [v.y * h for v in verts]
            bboxes.append([min(xs), min(ys), max(xs), max(ys)])
        if bboxes:
            page_bboxes[pn] = bboxes
    return page_bboxes


def _best_bbox_for_caption(
    cap_page: int,
    page_bboxes: dict[int, list[list[float]]],
    used_bboxes: set,
) -> list[float] | None:
    """캡션 페이지 또는 직전 페이지에서 가장 적합한 FIGURE bbox를 반환한다.

    used_bboxes: 이미 할당된 bbox tuple 집합 (중복 방지)
    """
    for pn in (cap_page, cap_page - 1):
        bboxes = page_bboxes.get(pn, [])
        candidates = [b for b in bboxes if tuple(b) not in used_bboxes]
        if candidates:
            return max(candidates, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return None


_DPI_SCALE = 300 / 72  # ≈ 4.167 → 300 DPI 렌더링


def _gemini_detect_figure_bbox(
    page_img_bytes: bytes,
    page_width_pt: float,
    page_height_pt: float,
    caption_text: str,
    project_id: str,
    location: str,
) -> list[float] | None:
    """
    Gemini 2.5 Flash Vision으로 페이지 이미지에서 그림 bbox를 감지한다.
    caption_text를 기준으로 해당 그림을 식별한다.

    Gemini Vision은 0~1000 정규화 좌표로 응답한다.
    변환 수식:
        X_pdf = (X_norm / 1000) × page_width_pt
        Y_pdf = (Y_norm / 1000) × page_height_pt

    반환: [x0, y0, x1, y1] (pt 단위, PyMuPDF 직접 사용 가능) 또는 None.
    """
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
    except ImportError:
        print("[extractor] vertexai 미설치 → Gemini fallback 불가", file=sys.stderr)
        return None

    # 캡션에서 그림 번호와 앞 60자만 사용 (프롬프트 길이 절약)
    cap_hint = caption_text[:80].strip()

    try:
        vertexai.init(project=project_id, location=location)
        model = GenerativeModel("gemini-2.5-flash")

        img_part = Part.from_data(data=page_img_bytes, mime_type="image/png")
        prompt = (
            "This is a page from a physics paper rendered as an image.\n"
            f"Find the diagram, graph, or illustration whose caption starts with: \"{cap_hint}\"\n\n"
            "Rules:\n"
            "- Return the bounding box of ONLY the visual area (plot, diagram, schematic).\n"
            "- DO NOT include the caption text in the bounding box.\n"
            "- DO include axis labels, tick marks, legends inside the figure.\n"
            "- If you cannot clearly identify a figure matching this caption on this page, "
            "return {\"x0\":0,\"y0\":0,\"x1\":0,\"y1\":0}.\n"
            "- Do NOT guess or return text paragraphs as figures.\n\n"
            "Return ONLY a JSON object with integer keys x0, y0, x1, y1 "
            "as normalized coordinates (0=top-left, 1000=bottom-right of the page image).\n"
            "Example: {\"x0\": 50, \"y0\": 80, \"x1\": 950, \"y1\": 520}"
        )
        response = model.generate_content([img_part, prompt])
        raw = response.text.strip()

        import json as _json
        raw = re.sub(r"```[a-z]*", "", raw).strip("`").strip()
        data = _json.loads(raw)
        x0_n, y0_n, x1_n, y1_n = data["x0"], data["y0"], data["x1"], data["y1"]

        if x1_n <= x0_n or y1_n <= y0_n:
            return None

        # 최소 크기 검증 (전체 페이지의 2% 미만이면 오탐으로 간주)
        if (x1_n - x0_n) < 20 or (y1_n - y0_n) < 20:
            return None

        # 0~1000 정규화 좌표 → pt 변환
        x0 = (x0_n / 1000) * page_width_pt
        y0 = (y0_n / 1000) * page_height_pt
        x1 = (x1_n / 1000) * page_width_pt
        y1 = (y1_n / 1000) * page_height_pt

        # Gemini는 경계를 보수적으로 잡는 경향이 있으므로 오른쪽/아래쪽만 여백 추가
        pad_x = page_width_pt  * 0.04   # 오른쪽 4%
        pad_y = page_height_pt * 0.025  # 아래쪽 2.5%
        x1 = min(page_width_pt,  x1 + pad_x)
        y1 = min(page_height_pt, y1 + pad_y)

        return [x0, y0, x1, y1]

    except Exception as e:
        print(f"[extractor] Gemini figure 감지 실패: {e}", file=sys.stderr)
        return None


def _crop_and_save(
    fitz_doc,
    page_idx: int,        # 0-based
    bbox_pt: list[float], # [x0,y0,x1,y1] in pt (PyMuPDF 좌표계)
    fig_path: str,
) -> None:
    """PyMuPDF로 bbox 영역을 300 DPI로 crop하여 PNG로 저장한다."""
    page = fitz_doc[page_idx]
    rect = fitz.Rect(bbox_pt)
    mat  = fitz.Matrix(_DPI_SCALE, _DPI_SCALE)   # 300 DPI
    pix  = page.get_pixmap(matrix=mat, clip=rect, colorspace=fitz.csRGB)
    pix.save(fig_path)


def _extract_raster_images_from_page(
    fitz_doc,       # fitz.Document (soft mask 추출에도 사용)
    page_idx: int,
    figures_dir: str,
    fig_num_start: int,
) -> list[dict]:
    """
    PyMuPDF page.get_images()로 페이지에 내장된 래스터 이미지를 직접 추출한다.

    반환: [{ "xref", "path", "width", "height" }, ...] 면적 내림차순 정렬.
    """
    page = fitz_doc[page_idx]
    img_list = page.get_images(full=True)
    results = []
    for i, img_info in enumerate(img_list):
        xref = img_info[0]
        try:
            base_img = fitz_doc.extract_image(xref)
        except Exception:
            continue
        w, h = base_img["width"], base_img["height"]
        # 너무 작은 이미지(아이콘, 로고 등) 제외 — 최소 100×100
        if w < 100 or h < 100:
            continue
        img_path = os.path.join(figures_dir, f"fig_{fig_num_start + i:03d}_raw.png")
        try:
            from PIL import Image
            import io as _io
            pil_img = Image.open(_io.BytesIO(base_img["image"])).convert("RGBA")
            smask_xref = base_img.get("smask", 0)
            if smask_xref > 0:
                # soft mask(알파 채널)를 적용하여 투명 영역을 흰색 배경으로 합성
                mask_data = fitz_doc.extract_image(smask_xref)
                mask_pil  = Image.open(_io.BytesIO(mask_data["image"])).convert("L")
                if mask_pil.size != pil_img.size:
                    mask_pil = mask_pil.resize(pil_img.size, Image.LANCZOS)
                pil_img.putalpha(mask_pil)
                bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                bg.paste(pil_img, mask=pil_img.split()[3])
                bg.save(img_path, "PNG")
            else:
                pil_img.convert("RGB").save(img_path, "PNG")
        except Exception:
            with open(img_path, "wb") as f:
                f.write(base_img["image"])
        results.append({"xref": xref, "path": img_path, "width": w, "height": h})
    # 면적 내림차순 정렬 (가장 큰 이미지가 본문 그림일 가능성 높음)
    results.sort(key=lambda x: x["width"] * x["height"], reverse=True)
    return results


def _yolo_detect_bboxes(
    page_img_path: str,
    page_w_pt: float,
    page_h_pt: float,
    img_w_px: int,
    img_h_px: int,
) -> tuple[list[list[float]], list[list[float]]]:
    """
    DocLayout-YOLO로 페이지 이미지에서 figure/table bbox(pt)를 감지한다.

    반환: (figure_bboxes, table_bboxes) — 각각 [[x0,y0,x1,y1], ...] pt 단위.
    """
    try:
        from doclayout_yolo import YOLOv10
        import huggingface_hub
    except ImportError:
        return [], []

    model_path = huggingface_hub.hf_hub_download(
        repo_id="juliozhao/DocLayout-YOLO-DocStructBench",
        filename="doclayout_yolo_docstructbench_imgsz1024.pt",
    )

    model = YOLOv10(model_path)
    det_res = model.predict(
        page_img_path,
        imgsz=1024,
        conf=0.5,
        device="cpu",
    )

    fig_bboxes: list[list[float]] = []
    tbl_bboxes: list[list[float]] = []
    for res in det_res:
        for box in res.boxes:
            cls_id = int(box.cls[0])
            label  = res.names.get(cls_id, "").lower()
            conf   = float(box.conf[0])
            if conf < 0.5:
                continue
            x0_px, y0_px, x1_px, y1_px = box.xyxy[0].tolist()
            x0 = (x0_px / img_w_px) * page_w_pt
            y0 = (y0_px / img_h_px) * page_h_pt
            x1 = (x1_px / img_w_px) * page_w_pt
            y1 = (y1_px / img_h_px) * page_h_pt
            if label == "figure":
                fig_bboxes.append([x0, y0, x1, y1])
            elif label == "table":
                tbl_bboxes.append([x0, y0, x1, y1])

    return fig_bboxes, tbl_bboxes


def _best_yolo_bbox_for_caption(
    cap_page: int,
    yolo_bboxes: dict[int, list[list[float]]],
    used_bboxes: set,
) -> list[float] | None:
    """캡션 페이지에서 아직 사용되지 않은 bbox를 y좌표 오름차순으로 반환한다.

    그림 번호 순서(Figure 1, 2, 3...)와 페이지 내 배치 순서(위→아래)를 일치시켜
    그림-캡션 번호 꼬임을 방지한다.
    """
    for pn in (cap_page, cap_page - 1):
        bboxes = yolo_bboxes.get(pn, [])
        candidates = [
            b for b in bboxes
            if tuple(b) not in used_bboxes
        ]
        if candidates:
            # 이미 2단 조판 순서로 정렬된 리스트 — 첫 번째 미사용 항목 반환
            return candidates[0]
    return None


def _extract_figures(
    pdf_path: str,
    document: documentai.Document,
    blocks: list[dict],
    figures_dir: str,
    config: dict | None = None,
) -> tuple[list[dict], dict[int, list[list[float]]]]:
    """
    그림 추출 전략 (우선순위 순):
    1. document.pages[].visual_elements (FIGURE 타입) bbox → PyMuPDF crop
    2. DocLayout-YOLO 탐지 → PyMuPDF crop
    3. visual_elements/YOLO 없는 캡션 → Gemini Vision 분석 → PyMuPDF crop

    저장 경로: figures_dir/fig_{N:03d}.png
    반환: ([{ "index", "path", "page", "bbox" }, ...], yolo_page_bboxes)
      yolo_page_bboxes: 페이지 번호 → figure bbox 리스트 (그림 내부 텍스트 필터링에 사용)
    """
    if config is None:
        config = {}

    fig_captions = [b for b in blocks if b["type"] == "figure_caption"]
    if not fig_captions:
        return [], {}

    # Document AI가 캡션을 레이아웃 순서가 아닌 다른 순서로 반환할 수 있으므로
    # 그림 번호(Figure N)로 정렬하여 fig_001 → Fig.1, fig_002 → Fig.2 매칭
    def _fig_sort_key(cap):
        m = re.search(r"(\d+)", cap.get("text", ""))
        return int(m.group(1)) if m else 9999
    fig_captions = sorted(fig_captions, key=_fig_sort_key)

    # ── 1) visual_elements bbox 수집 ─────────────────────────────────────
    page_bboxes = _collect_visual_element_bboxes(document)
    ve_pages = sorted(page_bboxes.keys())
    print(
        f"[extractor] visual_elements FIGURE 감지: {sum(len(v) for v in page_bboxes.values())}개 "
        f"(페이지: {ve_pages})",
        flush=True,
    )

    project_id = config.get("project_id", "")
    location   = config.get("location", "us-central1")

    figures: list[dict] = []

    # ── 2) YOLO: 모든 페이지 미리 탐지 ───────────────────────────────────
    # (캡션이 있는 페이지 + 직전 페이지만 처리)
    cap_pages_needed: set[int] = set()
    for cap in fig_captions:
        cap_pages_needed.add(cap["page"])
        cap_pages_needed.add(cap["page"] - 1)

    yolo_page_bboxes: dict[int, list[list[float]]] = {}   # figure bboxes
    yolo_table_bboxes: dict[int, list[list[float]]] = {}  # table bboxes
    yolo_available = False

    # 표 캡션 페이지도 YOLO 탐지 대상에 포함
    tbl_captions = [b for b in blocks if b["type"] in ("table", "table_caption")]
    for tc in tbl_captions:
        cap_pages_needed.add(tc["page"])

    with fitz.open(pdf_path) as _tmp_doc:
        for pn in sorted(cap_pages_needed):
            if pn < 1 or pn > _tmp_doc.page_count:
                continue
            fitz_p = _tmp_doc[pn - 1]
            page_w_pt = fitz_p.rect.width
            page_h_pt = fitz_p.rect.height
            pix = fitz_p.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB)
            tmp_img = os.path.join(figures_dir, f"_tmp_page_{pn}.png")
            pix.save(tmp_img)
            img_w_px, img_h_px = pix.width, pix.height

            fig_bboxes, tbl_bboxes = _yolo_detect_bboxes(
                tmp_img, page_w_pt, page_h_pt, img_w_px, img_h_px
            )
            try:
                os.remove(tmp_img)
            except OSError:
                pass

            if fig_bboxes:
                # 2단 조판: 왼쪽 컬럼(x_center < 절반) 먼저, 같은 컬럼 내 y 오름차순
                half_w = page_w_pt / 2
                fig_bboxes.sort(
                    key=lambda b: (0 if (b[0] + b[2]) / 2 < half_w else 1, b[1])
                )
                yolo_page_bboxes[pn] = fig_bboxes
                yolo_available = True
            if tbl_bboxes:
                yolo_table_bboxes[pn] = tbl_bboxes

    if yolo_available:
        total_yolo = sum(len(v) for v in yolo_page_bboxes.values())
        yolo_pages = sorted(yolo_page_bboxes.keys())
        print(
            f"[extractor] DocLayout-YOLO figure 감지: {total_yolo}개 "
            f"(페이지: {yolo_pages})",
            flush=True,
        )
    if yolo_table_bboxes:
        print(
            f"[extractor] DocLayout-YOLO table 감지: "
            f"{sum(len(v) for v in yolo_table_bboxes.values())}개 "
            f"(페이지: {sorted(yolo_table_bboxes.keys())})",
            flush=True,
        )
    if not yolo_available and not yolo_table_bboxes:
        print("[extractor] DocLayout-YOLO 미사용 (패키지 미설치 또는 탐지 없음)", flush=True)

    # ── 표 이미지 크롭 (YOLO table bbox → PNG) ───────────────────────────
    with fitz.open(pdf_path) as fitz_doc:
        for tbl_num, tbl_block in enumerate(tbl_captions, start=1):
            tbl_page = tbl_block["page"]
            tbl_path = os.path.join(figures_dir, f"table_{tbl_num:03d}.png")
            tbl_bboxes = yolo_table_bboxes.get(tbl_page, [])
            if tbl_bboxes:
                bbox = max(tbl_bboxes, key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
                try:
                    _crop_and_save(fitz_doc, tbl_page - 1, bbox, tbl_path)
                    tbl_block["table_img_path"] = tbl_path
                    print(
                        f"[extractor] 표 {tbl_num} (p.{tbl_page}): YOLO 크롭",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[extractor] 표 크롭 실패: {e}", file=sys.stderr)

    yolo_used: set = set()
    raster_cache: dict[int, list[dict]] = {}  # page_num → sorted img list (YOLO 없을 때 fallback)

    ve_used: set = set()
    with fitz.open(pdf_path) as fitz_doc:
        for fig_num, cap in enumerate(fig_captions, start=1):
            fig_path = os.path.join(figures_dir, f"fig_{fig_num:03d}.png")
            cap_page = cap["page"]

            # ── 전략 1: visual_elements bbox → 페이지 렌더링 크롭 ─────────
            bbox = _best_bbox_for_caption(cap_page, page_bboxes, ve_used)
            if bbox:
                try:
                    _crop_and_save(fitz_doc, cap_page - 1, bbox, fig_path)
                    ve_used.add(tuple(bbox))
                    figures.append({
                        "index": fig_num, "path": fig_path,
                        "page": cap_page, "bbox": bbox,
                    })
                    continue
                except Exception as e:
                    print(f"[extractor] 그림 {fig_num} crop 실패: {e}", file=sys.stderr)

            # ── 전략 2: YOLO bbox → 페이지 렌더링 크롭 ──────────────────
            # 래스터/벡터/합성 이미지 모두 올바르게 처리 (렌더링이 모든 케이스 처리)
            yolo_bbox = _best_yolo_bbox_for_caption(cap_page, yolo_page_bboxes, yolo_used)
            if yolo_bbox:
                try:
                    _crop_and_save(fitz_doc, cap_page - 1, yolo_bbox, fig_path)
                    yolo_used.add(tuple(yolo_bbox))
                    figures.append({
                        "index": fig_num, "path": fig_path,
                        "page": cap_page, "bbox": yolo_bbox,
                    })
                    print(
                        f"[extractor] 그림 {fig_num} (p.{cap_page}): YOLO 크롭",
                        flush=True,
                    )
                    continue
                except Exception as e:
                    print(f"[extractor] YOLO crop 실패: {e}", file=sys.stderr)

            # ── 전략 3: 래스터 직접 추출 (YOLO 미감지 페이지 fallback) ──
            raster_found = False
            for search_page in (cap_page, cap_page - 1):
                if search_page < 1:
                    continue
                if search_page not in raster_cache:
                    raster_cache[search_page] = _extract_raster_images_from_page(
                        fitz_doc, search_page - 1, figures_dir, fig_num
                    )
                raster_imgs = raster_cache[search_page]
                if raster_imgs:
                    img_info = raster_imgs.pop(0)
                    try:
                        import shutil
                        shutil.move(img_info["path"], fig_path)
                        figures.append({
                            "index": fig_num, "path": fig_path,
                            "page": cap_page, "bbox": [],
                        })
                        print(
                            f"[extractor] 그림 {fig_num} (p.{cap_page}): "
                            f"래스터 직접 추출 ({img_info['width']}×{img_info['height']}px)",
                            flush=True,
                        )
                        raster_found = True
                    except Exception as e:
                        print(f"[extractor] 래스터 추출 실패: {e}", file=sys.stderr)
                    break
            if raster_found:
                continue

            # ── 전략 3: Gemini Vision fallback ──────────────────────────
            print(
                f"[extractor] 그림 {fig_num} (p.{cap_page}): "
                f"YOLO 없음 → Gemini Vision 시도",
                flush=True,
            )
            fitz_page   = fitz_doc[cap_page - 1]
            page_w_pt   = fitz_page.rect.width
            page_h_pt   = fitz_page.rect.height

            page_pix    = fitz_page.get_pixmap(
                matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB
            )
            page_bytes  = page_pix.tobytes("png")

            gemini_bbox = _gemini_detect_figure_bbox(
                page_bytes, page_w_pt, page_h_pt, cap.get("text", ""), project_id, location
            )
            if gemini_bbox:
                try:
                    _crop_and_save(fitz_doc, cap_page - 1, gemini_bbox, fig_path)
                    figures.append({
                        "index": fig_num, "path": fig_path,
                        "page": cap_page, "bbox": gemini_bbox,
                    })
                    continue
                except Exception as e:
                    print(f"[extractor] Gemini crop 실패: {e}", file=sys.stderr)

            # 모두 실패 → 빈 항목 (캡션만 포함)
            figures.append({
                "index": fig_num, "path": fig_path,
                "page": cap_page, "bbox": [],
            })

    # 래스터 캐시에 남은 미사용 임시 파일 정리
    for img_list in raster_cache.values():
        for img_info in img_list:
            try:
                if os.path.exists(img_info["path"]):
                    os.remove(img_info["path"])
            except OSError:
                pass

    return figures, yolo_page_bboxes


# ---------------------------------------------------------------------------
# 그림 내부 텍스트 필터링
# ---------------------------------------------------------------------------

def _filter_figure_text_blocks(
    blocks: list[dict],
    yolo_page_bboxes: dict[int, list[list[float]]],
    pdf_path: str,
) -> list[dict]:
    """
    YOLO가 그림으로 탐지한 bbox 내부에 위치한 텍스트 블록을 본문에서 제거한다.

    DocAI blocks에는 bbox가 없으므로 PyMuPDF로 각 페이지의 텍스트 좌표를 조회한 후,
    중심점이 YOLO figure bbox 내에 있는 텍스트를 식별하여 제거한다.

    figure_caption / reference / title 등 보호 타입은 제거 대상에서 제외한다.
    """
    if not yolo_page_bboxes:
        return blocks

    # PyMuPDF로 관련 페이지의 그림 내부 텍스트 수집 (앞 60자로 키 생성)
    blocked_keys: set[str] = set()
    with fitz.open(pdf_path) as doc:
        for page_num, fig_bboxes in yolo_page_bboxes.items():
            if page_num < 1 or page_num > doc.page_count:
                continue
            page = doc[page_num - 1]
            for mb in page.get_text("blocks"):
                mb_text = mb[4].strip()
                if not mb_text:
                    continue
                mb_cx = (mb[0] + mb[2]) / 2
                mb_cy = (mb[1] + mb[3]) / 2
                for fb in fig_bboxes:
                    if fb[0] <= mb_cx <= fb[2] and fb[1] <= mb_cy <= fb[3]:
                        blocked_keys.add(mb_text[:60])
                        break

    if not blocked_keys:
        return blocks

    _PROTECTED = {"title", "authors", "figure_caption", "reference", "equation",
                  "abstract", "section", "subsection"}
    filtered = []
    for b in blocks:
        if b["type"] in _PROTECTED:
            filtered.append(b)
            continue
        if b.get("text", "").strip()[:60] in blocked_keys:
            continue  # 그림 내부 텍스트 → 제거
        filtered.append(b)

    removed = len(blocks) - len(filtered)
    if removed:
        print(f"[extractor] 그림 내부 텍스트 블록 {removed}개 제거", flush=True)
    return filtered


# ---------------------------------------------------------------------------
# 레이아웃 감지
# ---------------------------------------------------------------------------

def _detect_layout(pdf_path: str) -> str:
    """
    PyMuPDF 텍스트 블록의 x좌표 분포로 1단/2단 레이아웃을 감지한다.

    알고리즘:
      - 첫 2페이지의 텍스트 블록 수집
      - 페이지 상하 20~80% 구간 블록만 샘플 (헤더/푸터 제외)
      - 블록 중심 x < 페이지폭 * 0.55 비율 > 60% → twocolumn
      - 블록 수 5개 미만이면 onecolumn(기본값)
    반환: "twocolumn" 또는 "onecolumn"
    """
    try:
        with fitz.open(pdf_path) as doc:
            votes: list[str] = []
            for page_idx in range(min(3, doc.page_count)):
                page = doc[page_idx]
                pw = page.rect.width
                ph = page.rect.height
                blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)

                # 헤더/푸터 제외: y 중심이 페이지 20~80% 사이 블록만
                # 전체폭 블록(제목/초록 등, 폭 > 페이지폭 * 0.70) 제외
                sampled = [
                    b for b in blocks
                    if (b[1] + b[3]) / 2 > ph * 0.20
                    and (b[1] + b[3]) / 2 < ph * 0.80
                    and len(b[4].strip()) > 10  # 매우 짧은 단편 제외
                    and (b[2] - b[0]) <= pw * 0.70  # 전체폭 블록 제외
                ]

                if len(sampled) < 5:
                    votes.append("onecolumn")
                    continue

                left_count = sum(
                    1 for b in sampled
                    if (b[0] + b[2]) / 2 < pw * 0.55
                )
                ratio = left_count / len(sampled)

                if 0.30 <= ratio <= 0.70:
                    votes.append("twocolumn")
                else:
                    votes.append("onecolumn")

            if not votes:
                return "onecolumn"

            twocol_votes = votes.count("twocolumn")
            layout = "twocolumn" if twocol_votes > len(votes) / 2 else "onecolumn"
            print(f"[extractor] 레이아웃 감지: {layout} (투표: {votes})", flush=True)
            return layout

    except Exception as e:
        print(f"[extractor] 레이아웃 감지 실패, onecolumn으로 기본 설정: {e}", file=sys.stderr)
        return "onecolumn"


# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------

def _build_metadata(blocks: list[dict], pdf_path: str, total_pages: int) -> dict:
    title = ""
    authors = ""
    for b in blocks:
        if b["type"] == "title" and not title:
            title = b["text"]
        if b["type"] == "authors" and not authors:
            authors = b["text"]
        if title and authors:
            break
    return {
        "title":      title,
        "authors":    authors,
        "pages":      total_pages,
        "source_pdf": os.path.basename(pdf_path),
    }


# ---------------------------------------------------------------------------
# CLI 단독 실행 (테스트용)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import yaml

    if len(sys.argv) < 2:
        print("사용법: python extractor.py <pdf_path> [config.yaml]")
        sys.exit(1)

    pdf   = sys.argv[1]
    cfg_p = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"

    with open(cfg_p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    result = extract(pdf, cfg)

    out_path = os.path.join(cfg.get("output_dir", "output"), "paper.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # figure 블록을 body에서 제외한 실제 콘텐츠 블록 수
    content_blocks = [b for b in result["blocks"] if b["type"] != "figure"]
    print(
        f"[extractor] 완료: {result['metadata']['pages']}페이지, "
        f"{len(content_blocks)}블록, {len(result['figures'])}개 그림"
    )
    print(f"[extractor] 출력: {out_path}")
