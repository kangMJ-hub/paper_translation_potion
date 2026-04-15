"""
extractor.py — Physics-Trans v2.0
PDF → paper.json (pymupdf4llm / PyMuPDF)

3패스 파이프라인:
  1패스: 텍스트 블록 수집 + 분류
  2패스: 수식/표 후처리 (병합, 중복 제거 등)
  3패스: 그림 PNG 추출
"""

import json
import os
import re
import sys

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------

def extract(pdf_path: str, config: dict | None = None) -> dict:
    """
    PDF를 파싱하여 paper.json 형태의 dict를 반환한다.

    반환 구조:
      {
        "metadata": { "title", "authors", "pages", "source_pdf" },
        "blocks":   [ { "id", "type", "text", "page", "bbox", ... } ],
        "figures":  [ { "index", "path", "page", "bbox" } ]
      }
    """
    if config is None:
        config = {}

    output_dir = config.get("output_dir", "output")
    figures_dir = config.get("figures_dir", os.path.join(output_dir, "figures"))
    os.makedirs(figures_dir, exist_ok=True)

    blocks: list[dict] = []
    block_id = 0
    # 페이지별 단어 위치 데이터: { page_num: [ (x0,y0,x1,y1,text) ] }
    page_words: dict[int, list] = {}
    # 페이지별 이미지 블록 bbox (1-based page_num)
    page_image_bboxes: dict[int, list] = {}

    # ── 1패스: 텍스트 블록 수집 ──────────────────────────────────────────
    with fitz.open(pdf_path) as doc:
        total_pages = len(doc)

        for page_num, page in enumerate(doc):
            page_words[page_num] = page.get_text("words")
            text_dict = page.get_text("dict")

            img_bboxes = []
            for raw_block in text_dict.get("blocks", []):
                if raw_block.get("type") == 1:  # 이미지 블록
                    img_bboxes.append(list(raw_block.get("bbox", [])))
                    continue
                if raw_block.get("type") != 0:  # 0 = 텍스트 블록
                    continue

                max_size = 0.0
                line_texts: list[str] = []

                for line in raw_block.get("lines", []):
                    span_texts = []
                    for span in line.get("spans", []):
                        span_text = span.get("text", "")
                        # 제어 문자 제거 (탭/줄바꿈 제외)
                        span_text = "".join(
                            c for c in span_text if ord(c) >= 32 or c in "\t\n"
                        )
                        span_texts.append(span_text)
                        size = span.get("size", 0.0)
                        if size > max_size:
                            max_size = size
                    line = "".join(span_texts)
                    if line.strip():
                        line_texts.append(line)

                # 블록 내 하이픈 줄바꿈 처리
                text = _join_hyphenated_lines(line_texts)
                if not text:
                    continue

                # 컬럼 경계 하이픈 단어 복원 (이전 블록에 합침)
                if (blocks
                        and blocks[-1]["text"].endswith("-")
                        and re.match(r"^[a-z][a-z]{2,}[.,]?\s*$", text)):
                    blocks[-1]["text"] = blocks[-1]["text"][:-1] + text.strip()
                    continue

                block_type = _classify_block(text, max_size, block_id)
                if block_type == "skip":
                    continue

                blocks.append({
                    "id": f"block_{block_id:04d}",
                    "type": block_type,
                    "text": text,
                    "page": page_num + 1,
                    "_bbox": list(raw_block.get("bbox", [])),
                    "_font_size": max_size,
                })
                block_id += 1

            if img_bboxes:
                page_image_bboxes[page_num + 1] = img_bboxes

    # ── 2패스: 수식/표 후처리 ─────────────────────────────────────────────
    blocks = _merge_adjacent_equations(blocks)
    blocks = _fix_orphan_radicands(blocks)
    blocks = _detect_table_blocks(blocks, page_words)
    blocks = _remove_duplicate_blocks(blocks)
    blocks = _remove_running_headers(blocks)
    blocks = _clean_authors_block(blocks)

    # ── 3패스: 그림 PNG 추출 ──────────────────────────────────────────────
    figures = _extract_figures(pdf_path, blocks, figures_dir, page_image_bboxes)

    # figure_caption 블록에 figure_path / figure_index 연결
    fig_captions = [b for b in blocks
                    if b["type"] == "figure_caption"]
    for idx, (cap, fig) in enumerate(zip(fig_captions, figures), start=1):
        cap["figure_index"] = fig["index"]
        cap["figure_path"] = fig["path"]

    # 메타데이터 추출
    metadata = _build_metadata(blocks, pdf_path, total_pages)

    # bbox를 공개 필드로 이동, 내부 임시 필드 제거
    for b in blocks:
        b["bbox"] = b.pop("_bbox", [])
        b.pop("_font_size", None)

    return {
        "metadata": metadata,
        "blocks": blocks,
        "figures": figures,
    }


# ---------------------------------------------------------------------------
# 1패스 헬퍼
# ---------------------------------------------------------------------------

def _join_hyphenated_lines(line_texts: list[str]) -> str:
    """블록 내부 줄 목록을 하이픈 줄바꿈 규칙에 따라 하나의 문자열로 합친다."""
    text = ""
    for line in line_texts:
        if text.endswith("-") and line and line[0].islower():
            text = text[:-1] + line
        elif text:
            text = text + " " + line
        else:
            text = line
    return text.strip()


def _classify_block(text: str, font_size: float, position: int) -> str:
    """텍스트 블록의 타입을 분류한다. (레거시 classify_block() 로직 이식)"""
    stripped = text.strip()

    # ── 필터링 ────────────────────────────────────────────────────────────
    # 페이지 번호 (단독 숫자 1~3자리)
    if re.match(r"^\d{1,3}$", stripped):
        return "skip"

    # 단독 번호+점 (각주/소절 번호 파편)
    if re.match(r"^\d{1,3}\.$", stripped):
        return "skip"

    # 소문자 단일 토큰 파편 ("tively.", "ments." 등)
    if len(stripped) < 20 and re.match(r"^[a-z][a-z]{2,}[.,]?$", stripped):
        return "skip"

    # 괄호 시작 하이픈 단어 끝 파편 ("(ment).", "(ference)." 등)
    if len(stripped) < 30 and re.match(r"^\([a-z]{2,}\)[.,]?\s*$", stripped):
        return "skip"

    # arXiv 워터마크
    if re.match(r"^arXiv:\S+", stripped, re.IGNORECASE):
        return "skip"

    # PACS 번호
    if re.match(r"^PACS", stripped, re.IGNORECASE):
        return "skip"

    # OCR 쓰레기: 특수문자(알파벳·숫자·공백·기본 구두점 외) 비율 30% 초과
    _normal = len(re.findall(r"[\w\s.,;:!?()\[\]{}'\"/@#%&*+=<>\-]", stripped))
    if len(stripped) > 5 and _normal / len(stripped) < 0.70:
        return "skip"

    # ISSN/저널 인쇄 정보 (예: "0963-0252/92/020109+08 $04.50 ...")
    if re.match(r"^\d{4}-\d{4}/\d{2}/", stripped):
        return "skip"

    # 웹/뷰어 메타데이터
    _web_meta = [
        r"^페이지\s*\d+\s*/\s*\d+",
        r"^Page\s*\d+\s*of\s*\d+",
        r"^퍼머링크$", r"^Permalink$",
        r"^역사$", r"^History$",
        r"^탐색$", r"^Navigation$",
        r"^목차$", r"^Contents$",
        r"^Download\s*PDF", r"^PDF\s*Download",
        r"^\s*https?://",
        r"^DOI:\s*10\.\d{4}",
        r"^©\s*\d{4}",
        r"^Copyright\s*©",
        r"^\s*\d{4}\s+[A-Z][a-z]+\s+Publishing",
    ]
    for pat in _web_meta:
        if re.match(pat, stripped, re.IGNORECASE):
            return "skip"

    # ── 저자 이름 (position 초반, 폰트 작음) ─────────────────────────────
    if position < 5 and font_size < 11.5 and len(stripped) < 800:
        author_at_start = bool(re.match(r"^[A-Z][a-z]*\.?\s+[A-Z][a-z]", stripped))
        has_connector = "," in stripped or " and " in stripped.lower()
        if author_at_start and has_connector:
            return "authors"

    # ── 소속 필터 (position 초반에서만) ──────────────────────────────────
    if position < 8:
        _affil_kw = [
            r"\bDepartment\b", r"\bUniversity\b", r"\bInstitute\b",
            r"\bLaboratory\b", r"\bNational\b", r"\bCollege\b",
            r"\bCenter\b", r"\bSchool\s+of\b", r"\bFaculty\b",
            r"\bCorporation\b", r"\bCo\.\b", r"\bLtd\.\b", r"\bInc\.\b",
            r"\b\d{5,}\b",
        ]
        affil_score = sum(
            1 for kw in _affil_kw if re.search(kw, stripped, re.IGNORECASE)
        )
        if affil_score >= 2:
            return "skip"

    # ── 수신 날짜 형식 ────────────────────────────────────────────────────
    if re.match(r"^\d{4}년|\(Received|\(Submitted", stripped):
        return "paragraph"

    # ── 캡션 (수식 감지보다 먼저) ─────────────────────────────────────────
    if re.match(r"^(Fig\.|Figure|FIG\.)\s*(\d+|[IVX]+)", stripped, re.IGNORECASE):
        return "figure_caption"
    if re.match(r"^(Table|TABLE)\s*(\d+|[IVX]+)", stripped, re.IGNORECASE):
        return "table_caption"

    # ── 참고문헌 ──────────────────────────────────────────────────────────
    if re.match(r"^\[\d+\]", stripped) and position > 30:
        return "reference"

    # ── LaTeX 수식 ────────────────────────────────────────────────────────
    if re.search(r"\$.*?\$|\\begin\{equation\}|\\begin\{align", stripped):
        return "equation"

    # 유니코드 수학 기호 2개 이상 + 짧은 텍스트 + 한글 없음
    math_sym = len(re.findall(
        r"[ρσπθφψωαβγδεζηικλμνξ√∑∫∂∇≈≠≤≥×÷±∞†ˆ⟨⟩ǫ]", stripped
    ))
    if math_sym >= 2 and len(stripped) < 300 and not re.search(r"[가-힣]", stripped):
        return "equation"

    # ── 제목 ──────────────────────────────────────────────────────────────
    if font_size >= 11.0 and position < 5 and len(stripped) < 300:
        has_author_pattern = bool(
            re.search(r",\s*[A-Z]", stripped) or " and " in stripped.lower()
        )
        has_affil = bool(re.search(
            r"\b(Department|University|Institute|Laboratory|Corporation|Co\.|Ltd\.)\b",
            stripped, re.IGNORECASE
        ))
        if not has_author_pattern and not has_affil:
            return "title"

    # ── Abstract ──────────────────────────────────────────────────────────
    if re.match(r"^abstract", stripped, re.IGNORECASE):
        return "abstract"

    if position < 8 and font_size <= 9.5 and len(stripped) > 80:
        return "abstract"

    # ── 소절 / 절 ─────────────────────────────────────────────────────────
    if re.match(r"^\d+\.\d+\.?\s+[A-Z]", stripped) and len(stripped) < 150:
        return "subsection"

    if re.match(r"^\d+\.?\s+[A-Z]", stripped) and font_size >= 11.0 and len(stripped) < 120:
        return "section"
    if re.match(r"^[A-Z][A-Z\s]{3,}$", stripped) and font_size >= 11.0:
        return "section"

    return "paragraph"


# ---------------------------------------------------------------------------
# 2패스 후처리 헬퍼
# ---------------------------------------------------------------------------

def _merge_adjacent_equations(blocks: list[dict]) -> list[dict]:
    """같은 페이지에 연속으로 나타나는 수식 블록을 하나로 병합한다."""
    merged: list[dict] = []
    for block in blocks:
        if (block["type"] == "equation"
                and merged
                and merged[-1]["type"] == "equation"
                and merged[-1]["page"] == block["page"]):
            merged[-1]["text"] += "\n" + block["text"]
        else:
            merged.append(block)
    return merged


def _fix_orphan_radicands(blocks: list[dict]) -> list[dict]:
    """√ 기호 뒤 숫자가 다음 블록 첫머리로 분리된 경우 합친다."""
    result = list(blocks)
    i = 0
    while i < len(result) - 1:
        text = result[i]["text"]
        if not re.search(r"√\s*$", text):
            i += 1
            continue
        next_text = result[i + 1]["text"]
        m = re.match(r"^(\d+)(.*)", next_text, re.DOTALL)
        if not m:
            i += 1
            continue
        digit = m.group(1)
        rest = m.group(2)
        rest = re.sub(r"^[\s.]*(?:\[\d+\]\.?\s*)*", "", rest).strip()

        result[i] = dict(result[i])
        result[i]["text"] = re.sub(r"√(\s*)$", f"√{digit}", text)

        if rest:
            result[i + 1] = dict(result[i + 1])
            result[i + 1]["text"] = rest
        else:
            result.pop(i + 1)
        i += 1
    return result


def _detect_table_blocks(blocks: list[dict],
                          page_words: dict[int, list] | None = None) -> list[dict]:
    """TABLE 캡션 다음 데이터 블록을 table_data 타입으로 분류한다.
    page_words가 있으면 단어 위치 기반으로 행/열 구조를 재구성해 rows를 첨부한다."""
    if page_words is None:
        page_words = {}

    result: list[dict] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block["type"] == "table_caption":
            cap_page = block["page"] - 1   # 0-based
            cap_bbox = block.get("_bbox", [])
            matched_rows = None

            if cap_bbox and cap_page in page_words:
                matched_rows = _extract_table_by_words(
                    page_words[cap_page], cap_bbox
                )

            cap_block = dict(block)
            if matched_rows:
                cap_block["rows"] = matched_rows
            result.append(cap_block)
            i += 1

            # 텍스트 기반 table_data 블록도 수집 (fallback용)
            while i < len(blocks):
                nb = blocks[i]
                if nb["page"] != block["page"]:
                    break
                if nb["type"] in ("figure_caption", "table_caption", "section",
                                  "subsection", "paragraph"):
                    break
                nb = dict(nb)
                nb["type"] = "table_data"
                result.append(nb)
                i += 1
        else:
            result.append(block)
            i += 1
    return result


def _extract_table_by_words(words: list, cap_bbox: list) -> list[list[str]] | None:
    """
    단어 위치 기반 표 행/열 재구성.
    캡션 bbox 아래의 같은 컬럼 내 단어를 y축으로 행 클러스터링,
    첫 번째 행(헤더)의 x 위치로 열 경계를 설정한다.
    """
    cap_x0, cap_y0, cap_x1, cap_y1 = cap_bbox[:4]
    col_width = cap_x1 - cap_x0

    # 캡션 컬럼과 같은 x 범위, 캡션 하단 이후 단어 수집
    margin = col_width * 0.15
    tbl_words = [
        w for w in words
        if w[0] >= cap_x0 - margin
        and w[2] <= cap_x1 + margin
        and w[1] >= cap_y1 - 5
    ]
    if not tbl_words:
        return None

    # y 기준 행 클러스터링 (허용 오차 8pt)
    tbl_words.sort(key=lambda w: w[1])
    rows_raw: list[list] = []
    cur_y: float | None = None
    cur_row: list = []
    for w in tbl_words:
        if cur_y is None or w[1] - cur_y > 8:
            if cur_row:
                rows_raw.append(cur_row)
            cur_row = [w]
            cur_y = w[1]
        else:
            cur_row.append(w)
    if cur_row:
        rows_raw.append(cur_row)

    if len(rows_raw) < 2:
        return None

    # 헤더 행 단어의 x 중심으로 열 경계 결정
    header = sorted(rows_raw[0], key=lambda w: w[0])
    col_centers = [(w[0] + w[2]) / 2 for w in header]
    if not col_centers:
        return None

    # 열 경계: 인접 헤더 단어 사이 중간점
    boundaries = [cap_x0 - margin]
    for j in range(len(col_centers) - 1):
        boundaries.append((col_centers[j] + col_centers[j + 1]) / 2)
    boundaries.append(cap_x1 + margin)
    num_cols = len(col_centers)

    # 각 행을 열에 배분
    table_data: list[list[str]] = []
    for row_words in rows_raw:
        cells = [""] * num_cols
        for w in sorted(row_words, key=lambda x: x[0]):
            wx = (w[0] + w[2]) / 2
            col_idx = num_cols - 1
            for ci in range(num_cols):
                if wx < boundaries[ci + 1]:
                    col_idx = ci
                    break
            cells[col_idx] = (cells[col_idx] + " " + w[4]).strip()
        table_data.append(cells)

    return table_data if table_data else None


def _remove_duplicate_blocks(blocks: list[dict]) -> list[dict]:
    """동일 타입 텍스트가 중복 추출된 블록을 제거한다."""
    seen: dict[tuple, int] = {}
    result: list[dict] = []
    for block in blocks:
        if len(block["text"]) < 80:
            result.append(block)
            continue
        key = (block["type"], block["text"][:100].strip())
        if key in seen:
            continue
        seen[key] = len(result)
        result.append(block)
    return result


def _remove_running_headers(blocks: list[dict]) -> list[dict]:
    """
    여러 페이지에 반복 등장하는 짧은 텍스트(헤더/푸터)를 제거한다.
    동일 텍스트가 3개 이상 다른 페이지에 나타나면 전부 skip.
    """
    from collections import defaultdict
    text_pages: dict[str, set] = defaultdict(set)
    for b in blocks:
        if b["type"] in ("paragraph", "section", "subsection") and len(b["text"].strip()) < 120:
            key = b["text"].strip()[:80]
            text_pages[key].add(b["page"])
    repeated = {k for k, pages in text_pages.items() if len(pages) >= 3}
    return [b for b in blocks if b["text"].strip()[:80] not in repeated]


def _clean_authors_block(blocks: list[dict]) -> list[dict]:
    """authors 블록에서 소속 부분을 잘라내고 저자 이름만 남긴다."""
    _affil_kw = re.compile(
        r"\b(Department|University|Institute|Laboratory|National|College|"
        r"Center|School\s+of|Faculty|Corporation|Co\.|Ltd\.|Inc\.)\b",
        re.IGNORECASE,
    )
    result: list[dict] = []
    for block in blocks:
        if block["type"] != "authors":
            result.append(block)
            continue
        text = block["text"]
        m = _affil_kw.search(text)
        clean = text[: m.start()].strip().rstrip(",").strip() if m else text.strip()
        if clean:
            b = dict(block)
            b["text"] = clean
            result.append(b)
    return result


# ---------------------------------------------------------------------------
# 3패스: 그림 PNG 추출
# ---------------------------------------------------------------------------

def _extract_figures(
    pdf_path: str,
    blocks: list[dict],
    figures_dir: str,
    page_image_bboxes: dict[int, list] | None = None,
) -> list[dict]:
    """
    figure_caption 블록과 연결되는 그림을 PNG로 저장한다.

    전략:
      1) page_image_bboxes에서 캡션 근방의 이미지 블록(type=1)을 직접 사용 (정확)
      2) 이미지 블록이 없으면 텍스트 블록 위치 기반 추정 (fallback)

    저장 경로: figures_dir/fig_{N:03d}.png
    반환: [{ "index", "path", "page", "bbox" }, ...]
    """
    if page_image_bboxes is None:
        page_image_bboxes = {}

    fig_captions = [b for b in blocks if b["type"] == "figure_caption"]
    if not fig_captions:
        return []

    figures: list[dict] = []

    def _find_image_bbox(cap_page: int, cap_bbox: list, doc) -> tuple[fitz.Rect | None, int]:
        """캡션과 가장 관련 있는 이미지 블록 bbox를 찾는다. (rect, page_idx) 반환"""
        cap_y = cap_bbox[1]  # 캡션 상단 y

        # 탐색 대상: 같은 페이지 → 이전 페이지 순서
        for search_page in [cap_page, cap_page - 1]:
            if search_page < 1:
                continue
            bboxes = page_image_bboxes.get(search_page, [])
            if not bboxes:
                continue

            page_idx = search_page - 1
            page_rect = doc[page_idx].rect

            if search_page == cap_page:
                # 같은 페이지: 캡션보다 위에 있는 이미지 중 가장 가까운 것
                candidates = [b for b in bboxes if b[3] < cap_y + 10]
                if candidates:
                    best = max(candidates, key=lambda b: b[3])
                    return fitz.Rect(best), page_idx
            else:
                # 이전 페이지: 이미지 블록들을 합친 bounding box
                if bboxes:
                    x0 = min(b[0] for b in bboxes)
                    y0 = min(b[1] for b in bboxes)
                    x1 = max(b[2] for b in bboxes)
                    y1 = max(b[3] for b in bboxes)
                    # 페이지 여백 약간 추가
                    y0 = max(page_rect.y0, y0 - 5)
                    y1 = min(page_rect.y1, y1 + 5)
                    return fitz.Rect(x0, y0, x1, y1), page_idx
        return None, -1

    def _fallback_bbox(cap_page: int, cap_bbox: list, doc) -> tuple[fitz.Rect | None, int]:
        """이미지 블록 없을 때 텍스트 위치 기반 추정."""
        page_idx = cap_page - 1
        if page_idx >= len(doc) or not cap_bbox:
            return None, -1
        page = doc[page_idx]
        page_rect = page.rect
        cap_top_y = cap_bbox[1]
        cap_x0 = cap_bbox[0]

        mid_x = (page_rect.x0 + page_rect.x1) / 2
        if cap_x0 < mid_x:
            col_x0, col_x1 = page_rect.x0, mid_x
        else:
            col_x0, col_x1 = mid_x, page_rect.x1

        blocks_above = [
            b for b in blocks
            if b["page"] == cap_page
            and b.get("_bbox")
            and b["_bbox"][3] < cap_top_y - 5
            and b["_bbox"][0] >= col_x0 - 20
            and b["_bbox"][2] <= col_x1 + 20
            and b["type"] not in ("figure_caption", "table_caption")
        ]
        fig_top_y = max(b["_bbox"][3] for b in blocks_above) + 2 if blocks_above else page_rect.y0
        rect = fitz.Rect(col_x0, fig_top_y, col_x1, cap_top_y - 2)

        if rect.width < 30 or rect.height < 30:
            if page_idx > 0:
                prev_page = doc[page_idx - 1]
                prev_rect = prev_page.rect
                return fitz.Rect(col_x0, prev_rect.y0, col_x1, prev_rect.y1), page_idx - 1
            return None, -1
        return rect, page_idx

    with fitz.open(pdf_path) as doc:
        for fig_num, cap in enumerate(fig_captions, start=1):
            fig_path = os.path.join(figures_dir, f"fig_{fig_num:03d}.png")
            cap_bbox = cap.get("_bbox") or cap.get("bbox", [])
            cap_page = cap["page"]

            # 1) 이미지 블록 직접 탐색
            fig_rect, render_page_idx = _find_image_bbox(cap_page, cap_bbox, doc)

            # 2) fallback: 텍스트 위치 추정
            if fig_rect is None or fig_rect.width < 30 or fig_rect.height < 30:
                fig_rect, render_page_idx = _fallback_bbox(cap_page, cap_bbox, doc)

            if fig_rect is None or render_page_idx < 0:
                figures.append({"index": fig_num, "path": fig_path, "page": cap_page, "bbox": []})
                continue

            try:
                mat = fitz.Matrix(2, 2)
                pix = doc[render_page_idx].get_pixmap(matrix=mat, clip=fig_rect, colorspace=fitz.csRGB)
                pix.save(fig_path)
            except Exception as e:
                print(f"[extractor] 그림 {fig_num} 렌더링 실패: {e}", file=sys.stderr)

            figures.append({
                "index": fig_num,
                "path": fig_path,
                "page": cap_page,
                "bbox": list(fig_rect),
            })

    return figures


# ---------------------------------------------------------------------------
# 메타데이터 추출
# ---------------------------------------------------------------------------

def _build_metadata(blocks: list[dict], pdf_path: str, total_pages: int) -> dict:
    """블록 목록에서 제목/저자 정보를 추출해 metadata dict를 반환한다."""
    title = ""
    authors = ""
    for block in blocks:
        if block["type"] == "title" and not title:
            title = block["text"]
        if block["type"] == "authors" and not authors:
            authors = block["text"]
        if title and authors:
            break

    return {
        "title": title,
        "authors": authors,
        "pages": total_pages,
        "source_pdf": os.path.basename(pdf_path),
    }


# ---------------------------------------------------------------------------
# CLI 단독 실행 (테스트용)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import yaml

    if len(sys.argv) < 2:
        print("사용법: python extractor.py <pdf_path> [config.yaml]")
        sys.exit(1)

    pdf = sys.argv[1]
    cfg_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    result = extract(pdf, cfg)

    out_path = os.path.join(cfg.get("output_dir", "output"), "paper.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[extractor] 완료: {result['metadata']['pages']}페이지, "
          f"{len(result['blocks'])}블록, {len(result['figures'])}개 그림")
    print(f"[extractor] 출력: {out_path}")
