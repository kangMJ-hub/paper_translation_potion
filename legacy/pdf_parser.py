import fitz  # pymupdf
import json
import os
import re


def parse_pdf(pdf_path: str, output_dir: str, progress_callback=None) -> list:
    """PDF에서 텍스트 블록 및 이미지를 추출한다."""
    blocks = []
    block_id = 0

    figures_dir = os.path.join(output_dir, "figures")
    os.makedirs(figures_dir, exist_ok=True)

    # 1패스: 텍스트 블록 수집 (bbox 포함)
    with fitz.open(pdf_path) as doc:
        total_pages = len(doc)

        for page_num, page in enumerate(doc):
            if progress_callback:
                progress_callback(page_num, total_pages, f"PDF 파싱 중... ({page_num + 1}/{total_pages} 페이지)")

            text_dict = page.get_text("dict")
            for raw_block in text_dict.get("blocks", []):
                if raw_block.get("type") != 0:
                    continue

                max_size = 0.0
                line_texts = []
                for line in raw_block.get("lines", []):
                    span_texts = []
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            span_texts.append(span_text)
                        size = span.get("size", 0.0)
                        if size > max_size:
                            max_size = size
                    if span_texts:
                        line_texts.append(" ".join(span_texts))

                # 하이픈 줄바꿈 처리
                text = ""
                for line in line_texts:
                    if text.endswith("-") and line and line[0].islower():
                        text = text[:-1] + line
                    elif text:
                        text = text + " " + line
                    else:
                        text = line
                text = text.strip()
                if not text:
                    continue

                # 이전 블록이 하이픈으로 끝나는 경우: 소문자 파편을 이전 블록에 합침
                # (컬럼 경계에서 잘린 단어 복원, 예: "entangle-" + "ment." → "entanglement.")
                if (blocks and blocks[-1]['text'].endswith('-')
                        and re.match(r'^[a-z][a-z]{2,}[.,]?\s*$', text)):
                    blocks[-1]['text'] = blocks[-1]['text'][:-1] + text.strip()
                    continue

                block_type = classify_block(text, max_size, block_id)
                if block_type == "skip":
                    continue
                blocks.append({
                    "id": f"block_{block_id:04d}",
                    "type": block_type,
                    "text": text,
                    "page": page_num + 1,
                    "font_size": max_size,
                    "_bbox": raw_block.get("bbox"),  # 그림 렌더링용 임시 저장
                })
                block_id += 1

    # 2패스: 수식/표 병합·분류
    blocks = _merge_adjacent_equations(blocks)
    blocks = _fix_orphan_radicands(blocks)
    blocks = _detect_table_blocks(blocks)
    blocks = _remove_duplicate_blocks(blocks)
    blocks = _clean_authors_block(blocks)

    # 3패스: FIG. 캡션 위치 기반 그림 렌더링
    _render_figures(pdf_path, blocks, figures_dir)

    # bbox 임시 필드 제거
    for b in blocks:
        b.pop("_bbox", None)

    return blocks


def _render_figures(pdf_path: str, blocks: list, figures_dir: str):
    """FIG. 캡션 위치를 기준으로 그림 영역을 렌더링하여 저장한다."""
    import sys

    # FIG. 캡션만 순서대로 수집
    fig_captions = [
        b for b in blocks
        if b["type"] == "caption" and re.match(r'^(Fig\.|FIG\.)', b["text"], re.IGNORECASE)
    ]
    if not fig_captions:
        return

    with fitz.open(pdf_path) as doc:
        for fig_num, cap in enumerate(fig_captions, start=1):
            fig_path = os.path.join(figures_dir, f"fig_{fig_num:03d}.png")
            cap_bbox = cap.get("_bbox")
            page_idx = cap["page"] - 1

            if page_idx >= len(doc) or cap_bbox is None:
                continue

            page = doc[page_idx]
            page_rect = page.rect
            cap_top_y = cap_bbox[1]   # 캡션의 상단 y 좌표
            cap_x0 = cap_bbox[0]      # 캡션 왼쪽 x → 어느 단(column)인지 판별

            # 페이지 중앙 x 기준으로 좌/우 단 결정
            mid_x = (page_rect.x0 + page_rect.x1) / 2
            if cap_x0 < mid_x:
                col_x0, col_x1 = page_rect.x0, mid_x
            else:
                col_x0, col_x1 = mid_x, page_rect.x1

            # 같은 페이지·같은 단에서 캡션보다 위에 있는 텍스트 블록의 최하단 y 를 figure 상단으로 사용
            # (텍스트 영역을 그림으로 캡처하는 문제 방지)
            cap_page_num = cap["page"]
            blocks_above = [
                b for b in blocks
                if b["page"] == cap_page_num
                and b.get("_bbox") is not None
                and b["_bbox"][3] < cap_top_y - 5   # 블록 하단이 캡션 상단보다 위
                and b["_bbox"][0] >= col_x0 - 20    # 같은 단 범위 내
                and b["_bbox"][2] <= col_x1 + 20
                and b["type"] not in ("caption", "table_caption")
            ]
            if blocks_above:
                fig_top_y = max(b["_bbox"][3] for b in blocks_above) + 2
            else:
                fig_top_y = page_rect.y0

            # 해당 단의 마지막 텍스트 블록 하단 ~ 캡션 바로 위 영역
            fig_region = fitz.Rect(col_x0, fig_top_y, col_x1, cap_top_y - 2)

            # 같은 페이지에서 충분한 영역이 없으면 이전 페이지 전체 단 시도
            if (fig_region.width < 30 or fig_region.height < 30) and page_idx > 0:
                prev_page = doc[page_idx - 1]
                prev_rect = prev_page.rect
                # 이전 페이지에서도 텍스트 블록 제외하고 그림 영역만 캡처
                prev_page_num = page_idx  # page_idx = cap["page"] - 1, prev = page_idx - 1 + 1
                blocks_prev = [
                    b for b in blocks
                    if b["page"] == page_idx   # page_idx는 0-based, b["page"]는 1-based → page_idx == prev 1-based
                    and b.get("_bbox") is not None
                    and b["_bbox"][0] >= col_x0 - 20
                    and b["_bbox"][2] <= col_x1 + 20
                    and b["type"] not in ("caption", "table_caption")
                ]
                if blocks_prev:
                    prev_fig_top = max(b["_bbox"][3] for b in blocks_prev) + 2
                else:
                    prev_fig_top = prev_rect.y0
                fig_region = fitz.Rect(col_x0, prev_fig_top, col_x1, prev_rect.y1)
                render_page = prev_page
            else:
                render_page = page

            if fig_region.width < 30 or fig_region.height < 30:
                continue

            try:
                mat = fitz.Matrix(2, 2)
                pix = render_page.get_pixmap(matrix=mat, clip=fig_region, colorspace=fitz.csRGB)
                pix.save(fig_path)
            except Exception as e:
                print(f"[pdf_parser] 그림 {fig_num} 렌더링 실패: {e}", file=sys.stderr)


def _detect_table_blocks(blocks: list) -> list:
    """TABLE 캡션 다음에 오는 데이터 블록을 table_data 타입으로 분류한다."""
    result = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if (block['type'] == 'caption' and
                re.match(r'^(Table|TABLE)\s*(\d+|[IVX]+)', block['text'], re.IGNORECASE)):
            # 표 캡션을 table_caption으로 변경
            block = dict(block)
            block['type'] = 'table_caption'
            result.append(block)
            i += 1
            # 같은 페이지의 이후 equation 블록만 table_data로 분류 (paragraph/caption 만나면 중단)
            while i < len(blocks):
                nb = blocks[i]
                if nb['page'] != block['page']:
                    break
                if nb['type'] in ('caption', 'table_caption', 'section', 'subsection', 'paragraph'):
                    break
                nb = dict(nb)
                nb['type'] = 'table_data'
                result.append(nb)
                i += 1
        else:
            result.append(block)
            i += 1
    return result


def _clean_authors_block(blocks: list) -> list:
    """authors 블록에서 소속(affiliation) 부분을 잘라내고 저자 이름만 남긴다."""
    _affil_kw = re.compile(
        r'\b(Department|University|Institute|Laboratory|National|College|'
        r'Center|School\s+of|Faculty|Corporation|Co\.|Ltd\.|Inc\.)\b',
        re.IGNORECASE
    )
    result = []
    for block in blocks:
        if block['type'] != 'authors':
            result.append(block)
            continue
        text = block['text']
        # 소속 키워드가 처음 나타나는 위치에서 잘라냄
        m = _affil_kw.search(text)
        if m:
            clean_text = text[:m.start()].strip().rstrip(',').strip()
        else:
            clean_text = text.strip()
        if clean_text:
            b = dict(block)
            b['text'] = clean_text
            result.append(b)
    return result


def _remove_duplicate_blocks(blocks: list) -> list:
    """동일 타입의 텍스트 블록이 중복될 경우 나중 것을 제거한다.
    Abstract와 참고문헌처럼 PDF 파싱 과정에서 두 번 추출되는 블록을 처리한다.
    """
    seen: dict[tuple, int] = {}  # (type, normalized_text) → 첫 등장 index
    result = []
    for block in blocks:
        btype = block["type"]
        # 긴 블록만 중복 검사 (짧은 제목/수식 등은 제외)
        if len(block["text"]) < 80:
            result.append(block)
            continue
        # 텍스트 앞 100자를 키로 사용 (전체 비교는 너무 엄격)
        key = (btype, block["text"][:100].strip())
        if key in seen:
            continue  # 중복 — 건너뜀
        seen[key] = len(result)
        result.append(block)
    return result


def _fix_orphan_radicands(blocks: list) -> list:
    """√ 기호 뒤의 숫자가 다음 블록 첫머리로 분리된 경우 합친다.

    2단 PDF에서 '2/√' 와 '5. (C) Step ...' 처럼 블록이 잘리는 경우,
    √ 에 숫자를 붙이고 다음 블록에서 해당 숫자를 제거한다.
    """
    result = list(blocks)
    i = 0
    while i < len(result) - 1:
        text = result[i]['text']
        # 현재 블록 텍스트가 √ 로 끝나는지 확인 (뒤에 공백 허용)
        if not re.search(r'√\s*$', text):
            i += 1
            continue
        next_text = result[i + 1]['text']
        # 다음 블록이 숫자로 시작하는지 확인
        m = re.match(r'^(\d+)(.*)', next_text, re.DOTALL)
        if not m:
            i += 1
            continue
        digit = m.group(1)
        rest = m.group(2)
        # rest 앞의 인용 표기([12].) 및 구두점/공백 제거
        rest = re.sub(r'^[\s.]*(?:\[\d+\]\.?\s*)*', '', rest).strip()

        # 현재 블록의 √ 뒤에 숫자 추가
        new_text = re.sub(r'√(\s*)$', f'√{digit}', text)
        result[i] = dict(result[i])
        result[i]['text'] = new_text

        if rest:
            result[i + 1] = dict(result[i + 1])
            result[i + 1]['text'] = rest
        else:
            result.pop(i + 1)
        i += 1
    return result


def _merge_adjacent_equations(blocks: list) -> list:
    """같은 페이지에 연속으로 나타나는 수식 블록을 하나로 병합한다."""
    merged = []
    for block in blocks:
        if (block['type'] == 'equation' and merged and
                merged[-1]['type'] == 'equation' and
                merged[-1]['page'] == block['page']):
            merged[-1]['text'] += '\n' + block['text']
        else:
            merged.append(block)
    return merged


def classify_block(text: str, font_size: float, position: int) -> str:
    """텍스트 블록의 타입을 분류한다."""
    stripped = text.strip()

    # 페이지 번호 (단독 숫자 1~3자리) 필터링
    if re.match(r'^\d{1,3}$', stripped):
        return "skip"

    # 단독 번호+점 (각주 번호, 소절 번호 파편 등) 필터링 — "5.", "12." 등
    if re.match(r'^\d{1,3}\.$', stripped):
        return "skip"

    # 컬럼 넘침 단어 파편 필터링 — 소문자로 시작하는 짧은 단일 토큰 ("tively.", "ments." 등)
    if len(stripped) < 20 and re.match(r'^[a-z][a-z]{2,}[.,]?$', stripped):
        return "skip"

    # 괄호로 시작하는 단어 파편 필터링 — "(ment).", "(ference)." 등 하이픈 단어 끝 파편
    if len(stripped) < 30 and re.match(r'^\([a-z]{2,}\)[.,]?\s*$', stripped):
        return "skip"

    # arXiv 워터마크 필터링
    if re.match(r'^arXiv:\S+', stripped, re.IGNORECASE):
        return "skip"

    # PACS 번호 필터링
    if re.match(r'^PACS', stripped, re.IGNORECASE):
        return "skip"

    # 웹/뷰어 메타데이터 필터링 (PDF 뷰어 UI 텍스트, 스캔 워터마크 등)
    _web_meta_patterns = [
        r'^페이지\s*\d+\s*/\s*\d+',           # 페이지 X / Y
        r'^Page\s*\d+\s*of\s*\d+',            # Page X of Y
        r'^퍼머링크$',
        r'^Permalink$',
        r'^역사$',
        r'^History$',
        r'^탐색$',
        r'^Navigation$',
        r'^목차$',
        r'^Contents$',
        r'^Download\s*PDF',
        r'^PDF\s*Download',
        r'^\s*https?://',                      # URL만 있는 블록
        r'^DOI:\s*10\.\d{4}',                 # DOI 라인만 있는 경우
        r'^©\s*\d{4}',                        # 저작권 라인
        r'^Copyright\s*©',
        r'^\s*\d{4}\s+[A-Z][a-z]+\s+Publishing',  # 출판사 저작권
    ]
    for pat in _web_meta_patterns:
        if re.match(pat, stripped, re.IGNORECASE):
            return "skip"

    # 저자 이름 패턴 우선 감지 (소속 필터보다 먼저)
    # 반드시 텍스트 앞부분에서 시작해야 함 (본문 파편 오분류 방지)
    if position < 5 and font_size < 11.5 and len(stripped) < 800:
        # 텍스트가 "A. Lastname" 형식의 이름으로 시작해야 함
        author_at_start = bool(re.match(r'^[A-Z][a-z]*\.?\s+[A-Z][a-z]', stripped))
        has_connector = ',' in stripped or ' and ' in stripped.lower()
        if author_at_start and has_connector:
            return "authors"

    # 소속(affiliation) 필터링 — 저자 위치(position < 8)에서만 적용
    if position < 8:
        _affil_keywords = [
            r'\bDepartment\b', r'\bUniversity\b', r'\bInstitute\b',
            r'\bLaboratory\b', r'\bNational\b', r'\bCollege\b',
            r'\bCenter\b', r'\bSchool\s+of\b', r'\bFaculty\b',
            r'\bCorporation\b', r'\bCo\.\b', r'\bLtd\.\b', r'\bInc\.\b',
            r'\b\d{5,}\b',  # 우편번호
        ]
        affil_score = sum(1 for kw in _affil_keywords if re.search(kw, stripped, re.IGNORECASE))
        # 소속 키워드 2개 이상이면 skip (저자 이름이 아님)
        if affil_score >= 2:
            return "skip"

    # 날짜/수신 형식
    if re.match(r'^\d{4}년|\(Received|\(Submitted', stripped):
        return "paragraph"

    # 캡션 (Figure/Table + 숫자 또는 로마 숫자) — 수식 감지보다 먼저 체크
    if re.match(r'^(Fig\.|Figure|Table|TABLE|FIG\.)\s*(\d+|[IVX]+)', stripped, re.IGNORECASE):
        return "caption"

    # 참고문헌
    if re.match(r'^\[\d+\]', stripped) and position > 30:
        return "reference"
    if re.match(r'^\d+\.\s+[A-Z][a-z]', stripped) and position > 50:
        return "reference"

    # LaTeX 수식 ($...$, \begin{equation} 등)
    if re.search(r'\$.*?\$|\\begin\{equation\}|\\begin\{align', stripped):
        return "equation"

    # 수식처럼 보이는 텍스트 (유니코드 수학 기호 2개 이상 + 짧은 텍스트 + 한글 없음)
    math_sym = len(re.findall(r'[ρσπθφψωαβγδεζηικλμνξ√∑∫∂∇≈≠≤≥×÷±∞†ˆ⟨⟩ǫ]', stripped))
    if math_sym >= 2 and len(stripped) < 300 and not re.search(r'[가-힣]', stripped):
        return "equation"

    # 제목 (위치 0~4, 폰트 11pt 이상, 짧은 텍스트 — 소속/저자 제외)
    if font_size >= 11.0 and position < 5 and len(stripped) < 300:
        # 저자 패턴(콤마+and) 또는 소속 키워드가 없어야 제목
        has_author_pattern = bool(re.search(r',\s*[A-Z]', stripped) or ' and ' in stripped.lower())
        has_affil = bool(re.search(
            r'\b(Department|University|Institute|Laboratory|Corporation|Co\.|Ltd\.)\b',
            stripped, re.IGNORECASE
        ))
        if not has_author_pattern and not has_affil:
            return "title"

    # Abstract (명시적 키워드)
    if re.match(r'^abstract', stripped, re.IGNORECASE):
        return "abstract"

    # 논문 초반 작은 폰트 단락 = abstract (제목/저자 직후)
    if position < 8 and font_size <= 9.5 and len(stripped) > 80:
        return "abstract"

    # (구 저자 분류 로직 제거 — 상단의 저자 이름 패턴 감지로 대체됨)

    # 소절
    if re.match(r'^\d+\.\d+\.?\s+[A-Z]', stripped):
        return "subsection"

    # 절
    if re.match(r'^\d+\.?\s+[A-Z]', stripped) and font_size >= 11.0 and len(stripped) < 120:
        return "section"
    if re.match(r'^[A-Z][A-Z\s]{3,}$', stripped) and font_size >= 11.0:
        return "section"

    return "paragraph"


def protect_equations_in_text(text: str) -> tuple:
    """수식을 플레이스홀더로 치환한다."""
    placeholders = {}
    counter = [0]

    def replace_match(match):
        key = f"__EQ{counter[0]}__"
        placeholders[key] = match.group(0)
        counter[0] += 1
        return key

    # display math $$...$$
    text = re.sub(r'\$\$.*?\$\$', replace_match, text, flags=re.DOTALL)
    # \begin{equation}...\end{equation}
    text = re.sub(
        r'\\begin\{equation\}.*?\\end\{equation\}',
        replace_match, text, flags=re.DOTALL
    )
    # inline math $...$
    text = re.sub(r'\$[^$\n]+?\$', replace_match, text)

    return text, placeholders


def restore_equations(text: str, placeholders: dict) -> str:
    """플레이스홀더를 원래 수식으로 복원한다."""
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def escape_for_json(text: str) -> str:
    """JSON 저장용 문자열 정리 (제어문자 제거)."""
    import re
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def save_parsed_blocks(blocks: list, output_dir: str) -> str:
    """파싱 결과를 JSON 캐시에 저장한다."""
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "parsed_blocks.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False, indent=2)
    return cache_path


def load_parsed_blocks(output_dir: str):
    """캐시된 파싱 결과를 로드한다. 없으면 None 반환."""
    cache_path = os.path.join(output_dir, "cache", "parsed_blocks.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
