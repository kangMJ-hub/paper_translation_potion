"""
composer.py — Physics-Trans v2.0
translated.json → .tex → .pdf (Jinja2 + XeLaTeX)
"""

import os
import re
import subprocess
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils import escape_latex, fix_gemini_latex, unicode_math_to_inline_latex, wrap_bare_latex_in_text, protect_equations, restore_equations


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------

def compose(translated: dict, config: dict) -> str:
    """
    translated.json dict를 받아 .tex를 생성하고 XeLaTeX으로 컴파일한다.
    반환: 생성된 PDF 경로
    """
    # metadata.layout이 있으면 config의 layout 값을 덮어씀 (입력 논문 레이아웃 자동 반영)
    layout = translated.get("metadata", {}).get("layout", config.get("layout", "onecolumn"))
    config = dict(config)
    config["layout"] = layout

    tex_content = _render_template(translated, config)

    errors = _validate_latex(tex_content)
    if errors:
        print("[composer] LaTeX 검증 경고:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)

    output_dir = config.get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)

    source_pdf = translated.get("metadata", {}).get("source_pdf", "translated")
    base_name = os.path.splitext(source_pdf)[0] + "_번역"
    tex_path = os.path.join(output_dir, base_name + ".tex")

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_content)
    print(f"[composer] .tex 생성: {tex_path}")

    success, err_msg = _compile(tex_path, config)
    if not success:
        print(f"[composer] 컴파일 실패:\n{err_msg}", file=sys.stderr)
        raise RuntimeError(f"XeLaTeX 컴파일 실패: {tex_path}")

    pdf_path = os.path.splitext(tex_path)[0] + ".pdf"
    print(f"[composer] PDF 생성: {pdf_path}")
    return pdf_path


# ---------------------------------------------------------------------------
# Jinja2 렌더링
# ---------------------------------------------------------------------------

def _render_template(translated: dict, config: dict) -> str:
    """Jinja2 템플릿에 데이터를 주입하여 .tex 문자열을 반환한다."""
    template_file = config.get("template_file", "template.tex.j2")
    template_dir = os.path.dirname(os.path.abspath(template_file)) or "."
    template_name = os.path.basename(template_file)

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=False,           # LaTeX는 HTML 이스케이프 불필요
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        variable_start_string="(((",  # {{ 는 LaTeX에서 충돌하므로 변경
        variable_end_string=")))",
        block_start_string="((*",
        block_end_string="*))",
        comment_start_string="((#",
        comment_end_string="#))",
    )

    # 커스텀 필터 등록
    env.filters["format_equation"] = _filter_format_equation
    env.filters["format_figure"] = _filter_format_figure
    env.filters["escape_latex"] = escape_latex
    env.filters["escape_latex_text"] = _escape_latex_text
    env.filters["split_refs"] = _filter_split_refs
    env.filters["format_table"] = _filter_format_table
    env.filters["basename"] = os.path.basename
    env.filters["ref_num"] = _filter_ref_num
    env.filters["strip_ref_num"] = _filter_strip_ref_num
    env.filters["has_ref_num"] = lambda e: bool(re.match(r"^\[\d+\]|^\d{1,2}\)", e.strip()))

    template = env.get_template(template_name)

    # 블록 분류
    blocks = translated.get("blocks", [])
    metadata = translated.get("metadata", {})
    figures = translated.get("figures", [])

    abstract_blocks = [b for b in blocks if b["type"] == "abstract"]
    abstract_text = _escape_latex_text(
        fix_gemini_latex(
            "\n\n".join(
                b.get("translated_text") or b["text"] for b in abstract_blocks
            )
        )
    )

    # 제목 번역본 추출
    title_blocks = [b for b in blocks if b["type"] == "title"]
    if title_blocks:
        metadata = dict(metadata)
        metadata["translated_title"] = (
            title_blocks[0].get("translated_text") or metadata.get("title", "")
        )
    else:
        metadata = dict(metadata)
        metadata.setdefault("translated_title", metadata.get("title", ""))

    _ref_heading = re.compile(r"^(references|참고문헌|bibliography)$", re.IGNORECASE)

    # translated.json 캐시가 구 버전일 때를 대비해 여기서도 재분류 적용
    # 1) References 섹션 헤딩 이후 paragraph → reference
    # 2) 헤딩 없으면 citation 패턴 paragraph → reference
    _citation_pat = re.compile(
        r"^(?:\d{1,2}\])?"           # 잘린 번호 (예: "19]")
        r"\s*[A-Z][a-zA-Z\-]+\s+"   # 성(Last name)
        r"[A-Z]{1,3}\s+"             # 이니셜
        r"\d{4}\b",                  # 연도
    )
    reclassified: list[dict] = []
    in_ref_sec = False
    for b in blocks:
        if (b["type"] in ("section", "subsection", "paragraph")
                and _ref_heading.match(b.get("text", "").strip())):
            in_ref_sec = True
            continue
        if b["type"] == "paragraph":
            text = b.get("text", "").strip()
            is_citation = (
                in_ref_sec
                or _citation_pat.match(text)
                or re.match(r"^\d{1,2}\]\s*[A-Z]", text)  # "19] Welton..."
            )
            if is_citation:
                reclassified.append({**b, "type": "reference"})
                continue
            # 전체가 $...$ 수식인 단락 → equation으로 승격
            if _is_pure_eq_paragraph(b.get("translated_text") or text):
                reclassified.append({**b, "type": "equation"})
                continue
        reclassified.append(b)
    blocks = reclassified

    raw_body = [
        b for b in blocks
        if b["type"] not in ("title", "authors", "abstract", "reference", "footnote")
        and not (b["type"] in ("section", "subsection") and _ref_heading.match(b.get("text", "").strip()))
    ]
    # table_caption + table_data 쌍을 하나의 'table' 블록으로 합침
    body_blocks = []
    i = 0
    while i < len(raw_body):
        b = raw_body[i]
        if (b["type"] == "table_caption"
                and i + 1 < len(raw_body)
                and raw_body[i + 1]["type"] == "table_data"):
            data_block = raw_body[i + 1]
            data_text = (data_block.get("translated_text")
                         or data_block.get("text", ""))
            merged = dict(b)
            merged["type"] = "table"
            merged["data_text"] = data_text
            # translated.json에는 rows가 없으므로 data_text 줄 분리로 재구성
            if not merged.get("rows"):
                lines = [ln for ln in data_text.splitlines() if ln.strip()]
                if lines:
                    merged["rows"] = [[ln] for ln in lines]
            body_blocks.append(merged)
            i += 2
        elif b["type"] == "table_caption" and b.get("table_img_path"):
            # YOLO로 크롭된 표 이미지가 있으면 table 블록으로 승격
            merged = dict(b)
            merged["type"] = "table"
            body_blocks.append(merged)
            i += 1
        else:
            body_blocks.append(b)
            i += 1
    # paragraph 앞부분 $...(N)$ + 한국어 설명 → display equation + paragraph 분리
    split_body: list[dict] = []
    for b in body_blocks:
        if b["type"] == "paragraph":
            t = b.get("translated_text") or b.get("text", "")
            inner, eq_num, rest = _split_leading_equation(t)
            if inner:
                eq_text = f"{inner} \\tag{{{eq_num}}}" if eq_num else inner
                split_body.append({**b, "type": "equation",
                                   "translated_text": eq_text, "text": eq_text})
                split_body.append({**b, "type": "paragraph",
                                   "translated_text": rest, "text": rest})
                continue
        split_body.append(b)
    body_blocks = split_body

    def _ref_sort_key(b):
        m = re.match(r"^\[(\d+)\]|^(\d+)[).]", b.get("text", "").strip())
        if m:
            return int(m.group(1) or m.group(2))
        return 9999
    reference_blocks = sorted(
        [b for b in blocks if b["type"] == "reference"],
        key=_ref_sort_key,
    )
    # 참고문헌 스타일 감지: 하나라도 [N] / N) 번호가 있으면 numbered, 없으면 plain
    _has_num = lambda e: bool(re.match(r"^\[\d+\]|^\d{1,2}\)", e.strip()))
    ref_style = "plain"
    for rb in reference_blocks:
        for entry in _filter_split_refs(rb.get("text", "")):
            if _has_num(entry):
                ref_style = "numbered"
                break
        if ref_style == "numbered":
            break

    # figure index → path 매핑 (figure_caption 블록의 figure_path 우선 사용)
    fig_path_map: dict[int, str] = {}
    for fig in figures:
        fig_path_map[fig["index"]] = fig["path"]

    return template.render(
        metadata=metadata,
        abstract_text=abstract_text,
        body_blocks=body_blocks,
        reference_blocks=reference_blocks,
        ref_style=ref_style,
        fig_path_map=fig_path_map,
        config=config,
        main_font=config.get("main_font", "NanumMyeongjo"),
        sans_font=config.get("sans_font", "Malgun Gothic"),
        document_class=config.get("document_class", "revtex4-2"),
    )


# ---------------------------------------------------------------------------
# Jinja2 커스텀 필터
# ---------------------------------------------------------------------------

def _split_leading_equation(text: str) -> tuple[str, str | None, str]:
    """
    단락 텍스트가 $...(N)$ 으로 시작하고 뒤에 한국어 설명이 있을 때 분리한다.
    반환: (eq_inner, eq_num_or_None, rest_text)
    eq_inner가 빈 문자열이면 분리 불가.
    """
    stripped = (text or "").strip()
    m = re.match(
        r'^\$([^$]+)\$'           # 첫 번째 $...$
        r'[,.\s]*(?:\((\d+)\))?'  # 선택적 수식번호 (N)
        r'\s+(.+)',                # 나머지 텍스트 (최소 1자)
        stripped, re.DOTALL
    )
    if not m:
        return "", None, text
    inner = m.group(1)
    eq_num = m.group(2)
    rest = m.group(3).strip()
    # 나머지에 한국어가 있어야 의미 있는 분리
    if not re.search(r"[가-힣]", rest):
        return "", None, text
    return inner, eq_num, rest


def _check_brace_balance(text: str) -> bool:
    """LaTeX 텍스트에서 { } 균형 여부를 반환한다 (\\{ \\} 는 제외)."""
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in ("{", "}", "\\"):
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _is_pure_eq_paragraph(text: str) -> bool:
    """
    paragraph 블록이 display equation으로 승격돼야 하는지 판별한다.
    조건: 한국어 없음 + 전체 텍스트가 $...$ 하나로 구성 (뒤에 수식번호 허용)
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if re.search(r"[가-힣]", stripped):
        return False
    # $...$ 하나로 시작해서 끝나는 패턴 (뒤에 선택적으로 ,.(N) 허용)
    return bool(re.match(r"^\$[^$].+\$[,.\s]*(?:\(\d+\))?\s*$", stripped, re.DOTALL))


def _filter_format_equation(text: str) -> str:
    """수식 블록을 LaTeX equation / align 환경으로 포맷한다."""
    stripped = text.strip()
    if not stripped:
        return ""

    # 이미 equation/$$로 감싸진 경우 그대로
    if stripped.startswith(r"\begin{equation}") or stripped.startswith("$$"):
        return stripped
    # aligned/align/gather 환경은 equation으로 감싸야 math mode가 됨
    _INNER_ENV = re.compile(r"^\\begin\{(aligned|align\*?|gather\*?|multline\*?)\}")
    m_inner = _INNER_ENV.match(stripped)
    if m_inner:
        env = m_inner.group(1)
        end_tag = f"\\end{{{env}}}"
        if end_tag in stripped:
            result = f"\\begin{{equation}}\n{stripped}\n\\end{{equation}}"
            if not _check_brace_balance(result):
                print(f"[composer] equation {{ 불균형(inner env), 블록 생략: {text[:60]!r}", file=sys.stderr)
                return "% [수식 생략: LaTeX 중괄호 불균형]\n"
            return result
        # \end{...} 없으면 환경 태그 제거 후 일반 equation으로 처리
        stripped = _INNER_ENV.sub("", stripped).strip()

    # 합자 복원
    stripped = stripped.replace("ﬁ", "fi").replace("ﬂ", "fl")

    lines = stripped.split("\n")
    eq_lines: list[str] = []
    prose_lines: list[str] = []

    for line in lines:
        ls = line.strip()
        if not ls:
            continue
        has_latex = bool(re.search(r"\\[a-zA-Z]", ls))
        english_words = re.findall(r"\b[a-z]{4,}\b", ls)
        math_ops = re.findall(r"[=+\-×÷≈≠≤≥∑∫∂]", ls)
        korean = re.findall(r"[가-힣]", ls)

        if korean or (len(english_words) >= 4 and not has_latex and not math_ops):
            prose_lines.append(ls)
        else:
            if not prose_lines:
                eq_lines.append(ls)
            else:
                prose_lines.append(ls)

    eq_text = "\n".join(eq_lines).strip()
    # 번역기가 수식 텍스트에 $...$ 또는 $$...$$ 를 남긴 경우 제거
    eq_text = re.sub(r"^\$\$(.+?)\$\$$", r"\1", eq_text, flags=re.DOTALL)
    eq_text = re.sub(r"^\$(.+?)\$$", r"\1", eq_text, flags=re.DOTALL)
    # 수식 번호 앞 중복 괄호 및 뒤 stray $ 제거: "( (19)$" → "(19)"
    eq_text = re.sub(r'\(\s*(\(\d+[a-z]?\))\s*\$?', r'\1', eq_text)
    # 줄 끝 stray $ 제거 (수식 환경 내부)
    eq_text = re.sub(r'\$\s*$', '', eq_text, flags=re.MULTILINE)
    eq_text = eq_text.strip()

    # 측정값처럼 생긴 경우 (등호 없음, 숫자로 시작) → 인라인 텍스트로 처리
    # 예: "87\text{ nm} \pm 1.4\text{ nm} 3\sigma" 같은 그림 데이터 누출
    if (re.match(r"^\d", eq_text)
            and not re.search(r"[=≡≈∝]|\\approx|\\equiv|\\propto", eq_text)
            and "\n" not in eq_text.strip()):
        return _escape_latex_text(eq_text)

    eq_raw_lines = [l for l in eq_text.split("\n") if l.strip()]
    numbered = re.findall(r",?\s*\((\d+)\)\s*$", eq_text, re.MULTILINE)

    if len(eq_raw_lines) > 1 and numbered:
        align_lines = []
        for line in eq_raw_lines:
            line = re.sub(r",?\s*\((\d+)\)\s*$", r" \\tag{\1}", line.strip())
            align_lines.append(line)
        result = "\\begin{align}\n" + " \\\\\n".join(align_lines) + "\n\\end{align}"
    else:
        result = f"\\begin{{equation}}\n{eq_text}\n\\end{{equation}}"

    if prose_lines:
        prose = _escape_latex_text(" ".join(prose_lines))
        result += "\n\n" + prose

    # { } 균형 체크 — 불균형이면 컴파일 중단 방지를 위해 블록 생략
    if not _check_brace_balance(result):
        print(f"[composer] equation {{ 불균형, 블록 생략: {text[:60]!r}", file=sys.stderr)
        return "% [수식 생략: LaTeX 중괄호 불균형]\n"

    return result


def _filter_format_table(block: dict) -> str:
    """rows 데이터를 LaTeX tabular 환경으로 렌더링한다."""
    rows = block.get("rows", [])
    if not rows:
        return ""

    # 빈 셀 None → 빈 문자열, 열 수 통일
    cleaned = []
    max_cols = max((len(r) for r in rows), default=0)
    for row in rows:
        cells = [(c or "") for c in row]
        while len(cells) < max_cols:
            cells.append("")
        cleaned.append(cells)

    # 단일 컬럼(줄 분리 fallback)이면 넓은 p{} 컬럼 사용
    if max_cols == 1:
        col_spec = "p{0.85\\columnwidth}"
    else:
        col_spec = "c" * max_cols
    lines = [f"\\begin{{tabular}}{{{col_spec}}}", "\\hline"]
    for i, row in enumerate(cleaned):
        escaped = [_escape_latex_text(str(c)) for c in row]
        lines.append(" & ".join(escaped) + " \\\\")
        if i == 0:  # 헤더 행 아래 구분선
            lines.append("\\hline")
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    return "\n".join(lines)


def _filter_strip_ref_num(entry: str) -> str:
    """참고문헌 항목에서 앞의 [N] 또는 N) 번호 접두사를 제거한다."""
    s = re.sub(r"^\[\d+\]\s*", "", entry.strip())
    s = re.sub(r"^\d+\)\s*", "", s)
    return s


def _filter_ref_num(entry: str) -> str:
    """참고문헌 항목에서 원본 번호를 추출한다. [11] → 11, 11) → 11, 없으면 순번 해시."""
    m = re.match(r"^\[(\d+)\]", entry.strip())
    if m:
        return m.group(1)
    m = re.match(r"^(\d+)\)", entry.strip())
    if m:
        return m.group(1)
    return str(abs(hash(entry[:20])) % 10000)


def _filter_split_refs(text: str) -> list[str]:
    """레퍼런스 텍스트를 [N] 또는 N) 단위로 분리한다.
    번호 없는 블록은 그대로 1개 항목으로 반환한다."""
    if re.search(r"\[\d+\]", text):
        parts = re.split(r"(?=\[\d+\])", text.strip())
    elif re.search(r"(?<!\w)\d{1,2}\)\s*[A-Z]", text):
        parts = re.split(r"(?=(?<!\w)\d{1,2}\)\s*[A-Z])", text.strip())
    else:
        # 번호 없는 단일 항목 → 그대로 반환
        parts = [text.strip()]
    return [p.strip() for p in parts if p.strip()]


def _filter_format_figure(block: dict) -> str:
    """figure_caption 블록을 LaTeX figure 환경으로 포맷한다."""
    fig_num = block.get("figure_index", 0)
    fig_path = block.get("figure_path", "")
    caption_raw = block.get("translated_text") or block.get("text", "")

    # "그림 N:" / "Figure N:" 접두사 중복 방지
    caption = re.sub(
        r"^(그림|Figure|FIG\.?)\s*\d+\s*[:.]\s*", "", caption_raw, flags=re.IGNORECASE
    ).strip()
    escaped_caption = _escape_latex_text(caption)

    if fig_path and os.path.exists(fig_path):
        rel_path = "figures/" + os.path.basename(fig_path)
        image_content = (
            f"  \\adjustbox{{max totalsize={{\\columnwidth}}{{0.35\\textheight}}}}"
            f"{{\\includegraphics{{{rel_path}}}}}"
        )
    else:
        image_content = (
            "  \\fbox{\\parbox{0.9\\columnwidth}{\\centering "
            f"\\vspace{{2cm}} [그림 {fig_num}] \\vspace{{2cm}}}}}}"
        )

    return (
        "\\begin{figure}[H]\n"
        "\\centering\n"
        f"{image_content}\n"
        f"  \\caption{{{escaped_caption}}}\n"
        f"  \\label{{fig:{fig_num}}}\n"
        "\\end{figure}"
    )


# ---------------------------------------------------------------------------
# LaTeX 이스케이프 (수식 보존)
# ---------------------------------------------------------------------------

def _escape_latex_text(text: str) -> str:
    """인라인/디스플레이 수식을 보존하면서 LaTeX 특수문자를 이스케이프한다."""
    # HTML 태그 → LaTeX 변환 (Gemini가 출력한 <sup>, <sub> 등)
    text = re.sub(r"<sup>(.*?)</sup>", r"$^{\1}$", text)
    text = re.sub(r"<sub>(.*?)</sub>", r"$_{\1}$", text)
    text = re.sub(r"<[^>]+>", "", text)  # 나머지 HTML 태그 제거
    # PDF 추출 합자(ligature) → 일반 문자로 변환
    text = (text.replace("ﬁ", "fi").replace("ﬂ", "fl")
                .replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬄ", "ffl"))

    # math 환경 보호: \begin{matrix}...\end{matrix} 등이 escape_latex를 통과하지 않도록
    # placeholder는 LaTeX 특수문자를 포함하지 않으므로 escape_latex에 안전
    _MATH_ENV_RE = re.compile(
        r'\\begin\{(matrix|pmatrix|bmatrix|vmatrix|Vmatrix|array|cases|split|'
        r'aligned|alignat\*?|gathered|smallmatrix)\}'
        r'.*?'
        r'\\end\{\1\}',
        re.DOTALL,
    )
    # matrix/cases 등은 텍스트 모드에서 직접 사용 불가 → \[ \]로 감싸야 함
    _NEEDS_DISPLAY_WRAP = {'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'Vmatrix',
                           'array', 'cases', 'smallmatrix'}
    _env_store: dict[str, str] = {}
    _env_ctr = [0]
    def _save_env(m: re.Match) -> str:
        k = f"MATHENVPROTECT{_env_ctr[0]}END"
        env_name = m.group(1).rstrip('*')
        content = m.group(0)
        if env_name in _NEEDS_DISPLAY_WRAP:
            _env_store[k] = f'\\[\n{content}\n\\]'
        else:
            _env_store[k] = content
        _env_ctr[0] += 1
        return k
    text = _MATH_ENV_RE.sub(_save_env, text)

    # fix_gemini_latex: bare LaTeX 줄 전체를 $...$ 로 감싸기 (수식 없는 줄에만 적용)
    text = fix_gemini_latex(text)
    # 단락 내 stray 환경 태그 제거 (Gemini가 수식 환경 태그를 단락에 삽입한 경우)
    text = re.sub(r'\\end\{[^}]+\}', '', text)
    text = re.sub(r'\\begin\{(aligned|align\*?|gather\*?|multline\*?)\}', '', text)
    # \\ (N) 수식 줄바꿈+번호 패턴 → 번호만 남기기
    text = re.sub(r'\\\\\s*\((\d+)\)', r' (\1)', text)
    text = re.sub(r'\\\\(?=\s|$)', ' ', text)
    # $word \cmd...$ 패턴: 수식 앞 일반 영어 단어를 수식 밖으로 이동
    # 예: "$reduced \chi^{2}$" → "reduced $\chi^{2}$"
    text = re.sub(r'\$([a-z]+(?:\s+[a-z]+)*)\s+(\\[a-zA-Z])', r'\1 $\2', text)
    # bare LaTeX 명령어 / subscript/superscript → $...$ 감싸기 (이스케이프 전에 처리)
    text = wrap_bare_latex_in_text(text)
    # 1단계: 기존 $...$ 수식 + 보호된 math 환경 + \[...\] 분리 → 건드리지 않음
    _SPLIT_PAT = re.compile(r"(\$\$[^$]*?\$\$|\$[^$\n]+?\$|\\\[.*?\\\]|MATHENVPROTECT\d+END)", re.DOTALL)
    parts = _SPLIT_PAT.split(text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)  # 기존 수식 또는 보호된 환경: 그대로
        else:
            # Unicode 수식 기호 → $...$  (escape_latex 적용 전에 먼저 변환)
            part = unicode_math_to_inline_latex(part)
            # 2단계: 새로 생긴 $...$, \[...\] 도 보호 — 플레이스홀더 없이 다시 분리
            subparts = re.split(r"(\$\$[^$]*?\$\$|\$[^$\n]+?\$|\\\[.*?\\\])", part, flags=re.DOTALL)
            for j, subpart in enumerate(subparts):
                if j % 2 == 1:
                    result.append(subpart)  # 새 수식: 그대로
                else:
                    result.append(escape_latex(subpart))
    text = "".join(result)

    # 보호된 math 환경 복원
    for k, v in _env_store.items():
        text = text.replace(k, v)

    return text


# ---------------------------------------------------------------------------
# XeLaTeX 컴파일
# ---------------------------------------------------------------------------

def _compile(tex_path: str, config: dict) -> tuple[bool, str]:
    """
    XeLaTeX으로 2회 컴파일한다 (cross-reference 해소).
    반환: (성공여부, 오류메시지)
    """
    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    cmd = ["xelatex", "-interaction=nonstopmode", os.path.basename(tex_path)]

    for run in range(1, 3):
        try:
            import sys as _sys
            _cflags = subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0
            proc = subprocess.run(
                cmd,
                cwd=tex_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                creationflags=_cflags,
            )
        except FileNotFoundError:
            return False, "xelatex 명령어를 찾을 수 없습니다. XeLaTeX이 설치되어 있는지 확인하세요."
        except subprocess.TimeoutExpired:
            return False, "XeLaTeX 컴파일 타임아웃 (120초 초과)"

        if proc.returncode != 0:
            # PDF가 생성됐으면 경고만 내고 계속 진행 (bbl 없음 등 경미한 오류)
            pdf_path = os.path.splitext(tex_path)[0] + ".pdf"
            if os.path.exists(pdf_path):
                print(
                    f"[composer] XeLaTeX {run}회차: returncode={proc.returncode}이나 PDF 생성됨, 진행",
                    file=sys.stderr,
                )
                continue
            # 오류 메시지에서 핵심 라인만 추출
            error_lines = [
                line for line in proc.stdout.splitlines()
                if line.startswith("!") or "Error" in line
            ]
            err_summary = "\n".join(error_lines[:20]) or proc.stdout[-2000:]
            return False, f"컴파일 {run}회차 실패 (returncode={proc.returncode}):\n{err_summary}"

        print(f"[composer] XeLaTeX {run}회차 완료")

    return True, ""


# ---------------------------------------------------------------------------
# LaTeX 구조 검증
# ---------------------------------------------------------------------------

def _validate_latex(tex: str) -> list[str]:
    """
    $ 짝, {} 깊이, \\begin/\\end 짝을 검증한다.
    반환: 오류 목록 (빈 리스트 = 정상)
    """
    errors: list[str] = []

    # $ 짝 (\\$ 이스케이프 제외)
    dollar_count = len(re.findall(r"(?<!\\)\$", tex))
    if dollar_count % 2 != 0:
        errors.append(f"홀수 개의 $ 발견 ({dollar_count}개) — 수식 구분자 짝 불일치")

    # \begin / \end 짝
    begins = re.findall(r"\\begin\{(\w+\*?)\}", tex)
    ends = re.findall(r"\\end\{(\w+\*?)\}", tex)
    if sorted(begins) != sorted(ends):
        errors.append(f"\\begin/\\end 짝 불일치: begins={begins}, ends={ends}")

    # {} 균형
    depth = 0
    i = 0
    while i < len(tex):
        if tex[i] == "\\" and i + 1 < len(tex) and tex[i + 1] in ("\\", "{", "}"):
            i += 2
            continue
        if tex[i] == "{":
            depth += 1
        elif tex[i] == "}":
            depth -= 1
            if depth < 0:
                errors.append("닫는 } 가 여는 { 보다 많습니다.")
                depth = 0
        i += 1
    if depth != 0:
        errors.append(f"여는 {{ 가 닫히지 않았습니다 (미닫힌 깊이: {depth}).")

    return errors


# ---------------------------------------------------------------------------
# CLI 단독 실행 (테스트용)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import yaml

    if len(sys.argv) < 2:
        print("사용법: python composer.py <translated.json> [config.yaml]")
        sys.exit(1)

    json_path = sys.argv[1]
    cfg_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    pdf = compose(data, cfg)
    print(f"\n→ {pdf}")
