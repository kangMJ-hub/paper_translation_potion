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

    # ── 1패스: 텍스트 블록 수집 ──────────────────────────────────────────
    with fitz.open(pdf_path) as doc:
        total_pages = len(doc)

        for page_num, page in enumerate(doc):
            text_dict = page.get_text("dict")

            for raw_block in text_dict.get("blocks", []):
                if raw_block.get("type") != 0:  # 0 = 텍스트 블록
                    continue

                max_size = 0.0
                line_texts: list[str] = []

                for line in raw_block.get("lines", []):
                    span_texts = []
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        # 제어 문자 제거 (탭/줄바꿈 제외)
                        span_text = "".join(
                            c for c in span_text if ord(c) >= 32 or c in "\t\n"
                        )
                        if span_text:
                            span_texts.append(span_text)
                        size = span.get("size", 0.0)
                        if size > max_size:
                            max_size = size
                    if span_texts:
                        line_texts.append(" ".join(span_texts))

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

    # ── 2패스: 수식/표 후처리 ─────────────────────────────────────────────
    blocks = _merge_adjacent_equations(blocks)
    blocks = _fix_orphan_radicands(blocks)
    blocks = _detect_table_blocks(blocks)
    blocks = _remove_duplicate_blocks(blocks)
    blocks = _clean_authors_block(blocks)

    # ── 3패스: 그림 PNG 추출 ──────────────────────────────────────────────
    figures = _extract_figures(pdf_path, blocks, figures_dir)

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
    if re.match(r"^\d+\.\s+[A-Z][a-z]", stripped) and position > 50:
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
    if re.match(r"^\d+\.\d+\.?\s+[A-Z]", stripped):
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


def _detect_table_blocks(blocks: list[dict]) -> list[dict]:
    """TABLE 캡션 다음 데이터 블록을 table_data 타입으로 분류한다."""
    result: list[dict] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block["type"] == "table_caption":
            result.append(block)
            i += 1
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

def _extract_figures(pdf_path: str, blocks: list[dict], figures_dir: str) -> list[dict]:
    """
    figure_caption 블록의 bbox 위치를 기준으로 그림 영역을 계산,
    PNG로 저장한 뒤 figures 리스트를 반환한다.

    저장 경로: figures_dir/fig_{N:03d}.png
    반환: [{ "index", "path", "page", "bbox" }, ...]
    """
    fig_captions = [
        b for b in blocks
        if b["type"] == "figure_caption"
    ]
    if not fig_captions:
        return []

    figures: list[dict] = []

    with fitz.open(pdf_path) as doc:
        for fig_num, cap in enumerate(fig_captions, start=1):
            fig_path = os.path.join(figures_dir, f"fig_{fig_num:03d}.png")
            cap_bbox = cap.get("_bbox")
            page_idx = cap["page"] - 1

            if page_idx >= len(doc) or not cap_bbox:
                figures.append({
                    "index": fig_num,
                    "path": fig_path,
                    "page": cap["page"],
                    "bbox": [],
                })
                continue

            page = doc[page_idx]
            page_rect = page.rect
            cap_top_y = cap_bbox[1]
            cap_x0 = cap_bbox[0]

            # 좌/우 단 결정
            mid_x = (page_rect.x0 + page_rect.x1) / 2
            if cap_x0 < mid_x:
                col_x0, col_x1 = page_rect.x0, mid_x
            else:
                col_x0, col_x1 = mid_x, page_rect.x1

            cap_page_num = cap["page"]

            # 같은 페이지·같은 단에서 캡션보다 위에 있는 블록의 최하단 y → 그림 상단
            blocks_above = [
                b for b in blocks
                if b["page"] == cap_page_num
                and b.get("_bbox")
                and b["_bbox"][3] < cap_top_y - 5
                and b["_bbox"][0] >= col_x0 - 20
                and b["_bbox"][2] <= col_x1 + 20
                and b["type"] not in ("figure_caption", "table_caption")
            ]
            if blocks_above:
                fig_top_y = max(b["_bbox"][3] for b in blocks_above) + 2
            else:
                fig_top_y = page_rect.y0

            fig_region = fitz.Rect(col_x0, fig_top_y, col_x1, cap_top_y - 2)

            # 영역이 너무 작으면 이전 페이지 전체 단 시도
            if (fig_region.width < 30 or fig_region.height < 30) and page_idx > 0:
                prev_page = doc[page_idx - 1]
                prev_rect = prev_page.rect
                blocks_prev = [
                    b for b in blocks
                    if b["page"] == page_idx  # 1-based 기준 이전 페이지
                    and b.get("_bbox")
                    and b["_bbox"][0] >= col_x0 - 20
                    and b["_bbox"][2] <= col_x1 + 20
                    and b["type"] not in ("figure_caption", "table_caption")
                ]
                prev_top = (
                    max(b["_bbox"][3] for b in blocks_prev) + 2
                    if blocks_prev else prev_rect.y0
                )
                fig_region = fitz.Rect(col_x0, prev_top, col_x1, prev_rect.y1)
                render_page = prev_page
            else:
                render_page = page

            # 여전히 너무 작으면 건너뜀
            if fig_region.width < 30 or fig_region.height < 30:
                figures.append({
                    "index": fig_num,
                    "path": fig_path,
                    "page": cap["page"],
                    "bbox": list(fig_region),
                })
                continue

            try:
                mat = fitz.Matrix(2, 2)  # 2× 해상도
                pix = render_page.get_pixmap(matrix=mat, clip=fig_region, colorspace=fitz.csRGB)
                pix.save(fig_path)
            except Exception as e:
                print(f"[extractor] 그림 {fig_num} 렌더링 실패: {e}", file=sys.stderr)

            figures.append({
                "index": fig_num,
                "path": fig_path,
                "page": cap["page"],
                "bbox": list(fig_region),
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
