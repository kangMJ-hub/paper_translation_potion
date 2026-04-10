"""
composer.py — Physics-Trans v2.0
translated.json → .tex → .pdf (Jinja2 + XeLaTeX)
"""

import os
import re
import subprocess
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils import escape_latex, fix_gemini_latex, unicode_math_to_inline_latex


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------

def compose(translated: dict, config: dict) -> str:
    """
    translated.json dict를 받아 .tex를 생성하고 XeLaTeX으로 컴파일한다.
    반환: 생성된 PDF 경로
    """
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

    body_blocks = [
        b for b in blocks
        if b["type"] not in ("title", "authors", "abstract", "reference")
    ]
    reference_blocks = [b for b in blocks if b["type"] == "reference"]

    # figure index → path 매핑 (figure_caption 블록의 figure_path 우선 사용)
    fig_path_map: dict[int, str] = {}
    for fig in figures:
        fig_path_map[fig["index"]] = fig["path"]

    return template.render(
        metadata=metadata,
        abstract_text=abstract_text,
        body_blocks=body_blocks,
        reference_blocks=reference_blocks,
        fig_path_map=fig_path_map,
        config=config,
        main_font=config.get("main_font", "NanumMyeongjo"),
        sans_font=config.get("sans_font", "Malgun Gothic"),
        document_class=config.get("document_class", "revtex4-2"),
    )


# ---------------------------------------------------------------------------
# Jinja2 커스텀 필터
# ---------------------------------------------------------------------------

def _filter_format_equation(text: str) -> str:
    """수식 블록을 LaTeX equation / align 환경으로 포맷한다."""
    stripped = text.strip()
    if not stripped:
        return ""

    # 이미 환경으로 감싸진 경우 그대로
    if stripped.startswith(r"\begin{equation}") or stripped.startswith("$$"):
        return stripped

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

    return result


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
        image_content = f"  \\includegraphics[width=0.9\\columnwidth]{{{rel_path}}}"
    else:
        image_content = (
            "  \\fbox{\\parbox{0.9\\columnwidth}{\\centering "
            f"\\vspace{{2cm}} [그림 {fig_num}] \\vspace{{2cm}}}}}}"
        )

    return (
        "\\begin{figure}[htbp]\n"
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
    # PDF 추출 합자(ligature) → 일반 문자로 변환
    text = (text.replace("ﬁ", "fi").replace("ﬂ", "fl")
                .replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬄ", "ffl"))
    # 1단계: 기존 $...$ 수식 분리 → 수식 부분은 건드리지 않음
    parts = re.split(r"(\$\$[^$]*?\$\$|\$[^$\n]+?\$)", text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)  # 기존 수식: 그대로
        else:
            # Unicode 수식 기호 → $...$  (escape_latex 적용 전에 먼저 변환)
            part = unicode_math_to_inline_latex(part)
            # 2단계: 새로 생긴 $...$ 도 보호 — 플레이스홀더 없이 다시 분리
            subparts = re.split(r"(\$\$[^$]*?\$\$|\$[^$\n]+?\$)", part)
            for j, subpart in enumerate(subparts):
                if j % 2 == 1:
                    result.append(subpart)  # 새 수식: 그대로
                else:
                    result.append(escape_latex(subpart))
    return "".join(result)


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
            proc = subprocess.run(
                cmd,
                cwd=tex_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except FileNotFoundError:
            return False, "xelatex 명령어를 찾을 수 없습니다. XeLaTeX이 설치되어 있는지 확인하세요."
        except subprocess.TimeoutExpired:
            return False, "XeLaTeX 컴파일 타임아웃 (120초 초과)"

        if proc.returncode != 0:
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
