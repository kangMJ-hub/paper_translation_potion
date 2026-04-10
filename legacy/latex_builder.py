import os
import re

# Unicode 수학 기호 → LaTeX 변환 테이블 (텍스트 모드용: math mode로 감쌈)
_UNICODE_MATH = {
    'ˆ': r'$\hat{}$',
    '†': r'$\dagger$',
    '≪': r'$\ll$', '≫': r'$\gg$',
    '⟨': r'$\langle$', '⟩': r'$\rangle$',
    '⟦': r'$\llbracket$', '⟧': r'$\rrbracket$',
    '√': r'$\sqrt{}$',
    '∞': r'$\infty$', '∅': r'$\emptyset$',
    '∈': r'$\in$', '∉': r'$\notin$',
    '⊂': r'$\subset$', '⊃': r'$\supset$',
    '⊆': r'$\subseteq$', '⊇': r'$\supseteq$',
    '∩': r'$\cap$', '∪': r'$\cup$',
    '≤': r'$\leq$', '≥': r'$\geq$',
    '−': r'$-$',
    '≠': r'$\neq$', '≈': r'$\approx$',
    '≡': r'$\equiv$', '∝': r'$\propto$',
    '±': r'$\pm$', '∓': r'$\mp$',
    '×': r'$\times$', '÷': r'$\div$',
    '·': r'$\cdot$', '∘': r'$\circ$',
    '⊥': r'$\perp$', '∥': r'$\parallel$',
    '◦': r'$^\circ$', '°': r'$^\circ$',
    '∑': r'$\sum$', '∏': r'$\prod$',
    '∫': r'$\int$', '∂': r'$\partial$', '∇': r'$\nabla$',
    '→': r'$\rightarrow$', '←': r'$\leftarrow$',
    '↔': r'$\leftrightarrow$', '⇒': r'$\Rightarrow$',
    '⇔': r'$\Leftrightarrow$',
    '↑': r'$\uparrow$', '↓': r'$\downarrow$',
    # 그리스 소문자
    'α': r'$\alpha$', 'β': r'$\beta$', 'γ': r'$\gamma$',
    'δ': r'$\delta$', 'ε': r'$\epsilon$', 'ζ': r'$\zeta$',
    'η': r'$\eta$', 'θ': r'$\theta$', 'ϑ': r'$\vartheta$',
    'ι': r'$\iota$', 'κ': r'$\kappa$', 'λ': r'$\lambda$',
    'μ': r'$\mu$', 'ν': r'$\nu$', 'ξ': r'$\xi$',
    'π': r'$\pi$', 'ρ': r'$\rho$', 'σ': r'$\sigma$',
    'τ': r'$\tau$', 'υ': r'$\upsilon$', 'φ': r'$\varphi$',
    'ϕ': r'$\phi$', 'χ': r'$\chi$', 'ψ': r'$\psi$', 'ω': r'$\omega$',
    'ϵ': r'$\epsilon$', 'ϱ': r'$\varrho$', 'ϖ': r'$\varpi$',
    'ǫ': r'$\epsilon$',
    # 그리스 대문자
    'Γ': r'$\Gamma$', 'Δ': r'$\Delta$', 'Θ': r'$\Theta$',
    'Λ': r'$\Lambda$', 'Ξ': r'$\Xi$', 'Π': r'$\Pi$',
    'Σ': r'$\Sigma$', 'Υ': r'$\Upsilon$', 'Φ': r'$\Phi$',
    'Ψ': r'$\Psi$', 'Ω': r'$\Omega$',
    # 수학 이탤릭 (Mathematical Italic 블록 U+1D400–)
    '𝜏': r'$\tau$', '𝜑': r'$\varphi$', '𝜙': r'$\phi$',
    '𝜃': r'$\theta$', '𝜎': r'$\sigma$', '𝜌': r'$\rho$',
    '𝜇': r'$\mu$', '𝜈': r'$\nu$', '𝜆': r'$\lambda$',
    '𝜅': r'$\kappa$', '𝜂': r'$\eta$', '𝜁': r'$\zeta$',
    '𝜀': r'$\epsilon$', '𝛿': r'$\delta$', '𝛾': r'$\gamma$',
    '𝛽': r'$\beta$', '𝛼': r'$\alpha$', '𝜒': r'$\chi$',
    '𝜓': r'$\psi$', '𝜔': r'$\omega$',
}

# 수식 내부용 ($ 감싸기 없이 LaTeX 명령어만, 순수 명령어는 {} 추가로 뒤 문자와 분리)
_UNICODE_MATH_IN_MATH = {}
for _ch, _latex in _UNICODE_MATH.items():
    _cmd = _latex.strip('$')
    if re.match(r'^\\[a-zA-Z]+$', _cmd):  # \langle, \alpha 등 순수 명령어
        _cmd = _cmd + '{}'
    _UNICODE_MATH_IN_MATH[_ch] = _cmd
_UNICODE_MATH_IN_MATH['−'] = '-'  # U+2212 유니코드 마이너스 → ASCII 마이너스

# 분수 유니코드 문자 (텍스트 모드 및 수식 모드 공통 수동 등록)
_UNICODE_MATH['¼'] = r'$\frac{1}{4}$'
_UNICODE_MATH['½'] = r'$\frac{1}{2}$'
_UNICODE_MATH['¾'] = r'$\frac{3}{4}$'
_UNICODE_MATH['⅓'] = r'$\frac{1}{3}$'
_UNICODE_MATH['⅔'] = r'$\frac{2}{3}$'
_UNICODE_MATH['⅛'] = r'$\frac{1}{8}$'
_UNICODE_MATH['⅜'] = r'$\frac{3}{8}$'
_UNICODE_MATH['⅝'] = r'$\frac{5}{8}$'
_UNICODE_MATH['⅞'] = r'$\frac{7}{8}$'
_UNICODE_MATH_IN_MATH['¼'] = r'\frac{1}{4}'
_UNICODE_MATH_IN_MATH['½'] = r'\frac{1}{2}'
_UNICODE_MATH_IN_MATH['¾'] = r'\frac{3}{4}'
_UNICODE_MATH_IN_MATH['⅓'] = r'\frac{1}{3}'
_UNICODE_MATH_IN_MATH['⅔'] = r'\frac{2}{3}'
_UNICODE_MATH_IN_MATH['⅛'] = r'\frac{1}{8}'
_UNICODE_MATH_IN_MATH['⅜'] = r'\frac{3}{8}'
_UNICODE_MATH_IN_MATH['⅝'] = r'\frac{5}{8}'
_UNICODE_MATH_IN_MATH['⅞'] = r'\frac{7}{8}'


def _replace_unicode_math(text: str) -> str:
    """텍스트 모드에서 나타나는 Unicode 수학 기호를 LaTeX 명령어로 치환한다."""
    for ch, latex in _UNICODE_MATH.items():
        text = text.replace(ch, latex)
    return text


def _replace_unicode_math_in_math(text: str) -> str:
    """수식 모드($...$) 내부의 Unicode 수학 기호를 LaTeX 명령어로 치환한다 ($ 감싸기 없음)."""
    for ch, latex in _UNICODE_MATH_IN_MATH.items():
        text = text.replace(ch, latex)
    return text


def escape_latex(text: str) -> str:
    """LaTeX 특수문자를 이스케이프한다 (수식 모드 제외)."""
    # 순서 중요: 백슬래시를 가장 먼저 이스케이프해야 이후 치환이 중복 이스케이프되지 않음
    text = text.replace("\\", "\\textbackslash{}")
    text = text.replace("$", "\\$")
    text = text.replace("%", "\\%")
    text = text.replace("&", "\\&")
    text = text.replace("#", "\\#")
    text = text.replace("_", "\\_")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("^", "\\^{}")
    text = text.replace("~", "\\textasciitilde{}")
    return text


def escape_latex_text(text: str) -> str:
    """인라인 수식($...$)과 디스플레이 수식($$...$$)을 보존하면서 LaTeX 특수문자를 이스케이프한다."""
    # $$...$$ 를 먼저 처리한 뒤 $...$ 처리 (순서 중요)
    parts = re.split(r'(\$\$[^$]*?\$\$|\$[^$\n]+?\$)', text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 0:  # 수식 밖 — 이스케이프 후 유니코드 수학 기호 치환
            result.append(_replace_unicode_math(escape_latex(part)))
        else:  # 수식 안 — 유니코드 수학 기호만 LaTeX 명령어로 치환 ($ 감싸기 없음)
            result.append(_replace_unicode_math_in_math(part))
    return "".join(result)


def _fix_text_block(m: re.Match) -> str:
    """\\text{} 안에 있는 수학 명령어(\\mu, \\lambda 등)를 밖으로 꺼낸다."""
    inner = m.group(1)
    # 수학 명령어가 없으면 그대로
    if not re.search(r'\\[a-zA-Z]+', inner):
        return m.group(0)
    # 수학 명령어 기준으로 분리: \text{A \mu B} → \text{A}\mu\mathrm{B}
    parts = re.split(r'(\\[a-zA-Z]+)', inner)
    result = []
    text_buf = ''
    for part in parts:
        if re.match(r'^\\[a-zA-Z]+$', part):
            if text_buf.strip():
                result.append(f'\\text{{{text_buf}}}')
            text_buf = ''
            result.append(part)
        else:
            text_buf += part
    if text_buf.strip():
        result.append(f'\\mathrm{{{text_buf.strip()}}}')
    return ''.join(result)


def strip_control_chars(text: str) -> str:
    """PDF 파싱 과정에서 유입된 제어 문자(NUL, SOH 등)를 제거한다."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)


def fix_gemini_latex(text: str) -> str:
    """Gemini가 생성한 잘못된 LaTeX 패턴을 수정한다."""
    # \mathcal은 대문자 A-Z만 허용 — 소문자나 명령어가 들어오면 제거
    text = re.sub(r'\$\\mathcal\{(\\[a-z]+)\}\$', r'$\1$', text)
    text = re.sub(r'\\mathcal\{(\\[a-z]+)\}', r'\1', text)
    # \sqrt 뒤에 공백+내용이 있으면 {} 로 묶기 (\sqrt 5 → \sqrt{5})
    # 빈 \sqrt{} 는 건드리지 않음 (이미 Gemini가 잘못 생성한 경우 프롬프트에서 방지)
    text = re.sub(r'\\sqrt\s+(\S)', r'\\sqrt{\1}', text)
    # \text{} 안에 수학 명령어(\mu, \lambda 등)가 있으면 밖으로 이동
    text = re.sub(r'\\text\{([^}]*\\[a-zA-Z]+[^}]*)\}', _fix_text_block, text)

    # $로 감싸지지 않은 bare LaTeX 수식 명령어를 수식 모드로 감싸기
    lines = text.split('\n')
    wrapped = []
    for line in lines:
        stripped = line.strip()
        # 이미 수식이 있거나 한국어 있으면 그대로
        if '$' in stripped or '\\begin{' in stripped:
            wrapped.append(line)
            continue
        # LaTeX 명령어 개수 vs 일반 단어 개수 비교
        latex_cmds = re.findall(r'\\[a-zA-Z]+', stripped)
        korean = re.findall(r'[가-힣]', stripped)
        normal_words = re.findall(r'\b[a-zA-Z]{3,}\b', stripped)
        if len(latex_cmds) >= 2 and not korean and len(stripped) < 300:
            wrapped.append(f'${stripped}$')
        else:
            wrapped.append(line)
    text = '\n'.join(wrapped)

    return text


def build_preamble(documentclass: str, font_main: str, font_sans: str, config_latex: dict = None) -> str:
    """LaTeX 프리앰블을 생성한다."""
    if config_latex is None:
        config_latex = {}
    return (
        f"\\documentclass{{{documentclass}}}\n"
        "\\usepackage{fontspec}\n"
        "\\usepackage{kotex}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage{amssymb}\n"
        "\\usepackage{graphicx}\n"
        "\\usepackage{float}\n"
        "\\usepackage{hyperref}\n"
        "\\usepackage{booktabs}\n"
        "\\usepackage{geometry}\n"
        "\\geometry{margin=2.5cm}\n"
        "\n"
        f"\\setmainfont{{{font_main}}}\n"
        f"\\setsansfont{{{font_sans}}}\n"
        "\\renewcommand{\\figurename}{그림}\n"
        "\\renewcommand{\\tablename}{표}\n"
        "\n"
    )


def _normalize_table_text(text: str) -> str:
    """표 텍스트의 LaTeX 마크업을 제거하고 파싱 가능한 순수 텍스트로 변환한다."""
    # \text{...} → 내부 텍스트
    text = re.sub(r'\\text\{([^}]*)\}', r'\1', text)
    # \mathrm{...}, \mathbf{...} 등 → 내부 텍스트
    text = re.sub(r'\\math\w+\{([^}]*)\}', r'\1', text)
    # \pm → ±, − → -
    text = re.sub(r'\\pm', '±', text)
    text = re.sub(r'−', '-', text)
    # 각도: $N^\circ$ 또는 $N^{\circ}$ → N°
    text = re.sub(r'\$\s*(-?\d+\.?\d*)\s*\^\{?\\circ\}?\s*\$', r'\1°', text)
    # 각도: N^\circ ($ 없이) → N°
    text = re.sub(r'(-?\d+\.?\d*)\s*\^\{?\\circ\}?', r'\1°', text)
    # ◦ → °
    text = re.sub(r'\s*◦', '°', text)
    # 모든 $ 제거 (파싱용 — 이후 행 재조립 시 다시 추가)
    text = text.replace('$', '')
    # \lambda_s, \theta_s 등 남은 LaTeX 명령어 제거
    text = re.sub(r'\\[a-zA-Z]+(?:_\w)?', ' ', text)
    # {} 제거
    text = text.replace('{', '').replace('}', '')
    # 숫자와 소수점 사이 공백 제거: 0 . 670 → 0.670
    text = re.sub(r'(\d)\s+\.\s+(\d)', r'\1.\2', text)
    # ± 주변 공백 제거
    text = re.sub(r'\s*±\s*', '±', text)
    # 다중 공백 정리
    text = re.sub(r' {2,}', ' ', text)
    return text


def _build_table_rows(header_text: str, data_texts: list) -> str:
    """표 헤더와 데이터 텍스트로 tabular 환경 내용을 생성한다."""
    # 헤더 LaTeX 변환
    header_map = {
        'λ s': r'$\lambda_s$', 'λs': r'$\lambda_s$',
        'θ s': r'$\theta_s$', 'θs': r'$\theta_s$',
        'θ i': r'$\theta_i$', 'θi': r'$\theta_i$',
        'E ( θ s , θ i )': r'$E(\theta_s, \theta_i)$',
        'E(θ s,θ i)': r'$E(\theta_s, \theta_i)$',
    }
    header_latex = header_text
    for src, dst in header_map.items():
        header_latex = header_latex.replace(src, dst)
    # 나머지 토큰을 & 로 구분 (공백 기준 4개 열)
    header_cols = [c.strip() for c in re.split(r'\s{2,}', header_latex.strip())]
    if len(header_cols) < 4:
        header_cols = header_latex.strip().split()[:4]
    header_line = ' & '.join(header_cols) + r' \\'

    # 데이터 정규화
    combined = ' '.join(data_texts)
    combined = _normalize_table_text(combined)

    # 각 행 패턴: angle angle value±err 형식
    row_pattern = re.compile(
        r'(-?\d+\.?\d*°)\s+(-?\d+\.?\d*°)\s+(-?\d+\.?\d*±\d+\.?\d*)'
    )
    wavelength_pattern = re.compile(r'([\d.]+\s*(?:nm|µm|μm))')
    s_pattern = re.compile(r'S\s*=\s*(-?\d+\.?\d*±\d+\.?\d*)')

    rows = []
    current_lambda = ''
    pos = 0
    for m in row_pattern.finditer(combined):
        # 이 매치 이전 텍스트에서 파장 찾기
        before = combined[pos:m.start()]
        wl = wavelength_pattern.search(before)
        if wl:
            current_lambda = wl.group(1).strip()
        t_s, t_i, e_val = m.group(1), m.group(2), m.group(3)
        lam_cell = f'${current_lambda}$' if current_lambda else ''
        e_latex = e_val.replace('±', r' \pm ')
        rows.append(f'{lam_cell} & ${t_s}$ & ${t_i}$ & ${e_latex}$' + r' \\')
        current_lambda = ''  # 한 행에 한 번만 표시
        pos = m.end()

    # S = ... 값 찾기
    s_matches = s_pattern.findall(combined)
    s_rows = ''
    for sv in s_matches:
        sv_latex = sv.replace('±', r' \pm ')
        s_rows += f'\\multicolumn{{4}}{{r}}{{$S = {sv_latex}$}} \\\\\n'

    if not rows:
        # 파싱 실패 시 원본 텍스트 그대로
        return None

    lines = [header_line, r'\hline']
    lines += rows
    if s_rows:
        lines.append(r'\hline')
        lines.append(s_rows.strip())

    return '\n'.join(lines)


def format_table(caption: str, data_blocks: list) -> str:
    """표 환경(table + tabular)을 생성한다."""
    if not data_blocks:
        return f'\\textbf{{{escape_latex(caption)}}}'

    texts = [b.get("translated_text") or b["text"] for b in data_blocks]
    header_text = texts[0] if texts else ''
    data_texts = texts[1:] if len(texts) > 1 else texts

    escaped_caption = escape_latex_text(fix_gemini_latex(strip_control_chars(caption)))
    table_content = _build_table_rows(header_text, data_texts)

    if table_content is None:
        # tabular 파싱 실패 → 각 행을 줄 단위로 나열 (블록 내 줄바꿈도 분리)
        rows_tex = []
        for txt in texts:
            clean = strip_control_chars(txt)
            for line in clean.split('\n'):
                line = line.strip()
                if line:
                    rows_tex.append(escape_latex_text(fix_gemini_latex(line)))
        raw = "\\\\\n".join(rows_tex)
        return (
            "\\begin{table}[htbp]\n\\centering\n"
            f"\\caption{{{escaped_caption}}}\n"
            "\\begin{tabular}{l}\n"
            f"{raw}\n"
            "\\end{tabular}\n"
            "\\end{table}"
        )

    return (
        "\\begin{table}[htbp]\n\\centering\n"
        f"\\caption{{{escaped_caption}}}\n"
        "\\begin{tabular}{cccc}\n"
        "\\hline\n"
        f"{table_content}\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "\\end{table}"
    )


def format_equation(text: str) -> str:
    """수식 블록을 LaTeX equation 환경으로 포맷한다.
    Gemini가 이미 LaTeX로 변환한 내용 또는 원문 텍스트를 받아 equation 환경으로 감싼다.
    """
    stripped = text.strip()
    if not stripped:
        return ''

    # 이미 equation 환경이면 그대로 반환
    if stripped.startswith("\\begin{equation}") or stripped.startswith("$$"):
        return stripped

    # fi, fl 합자 복원
    stripped = stripped.replace('ﬁ', 'fi').replace('ﬂ', 'fl')

    # 수식 줄과 산문(설명) 줄 분리
    # 단, LaTeX 명령어가 있는 줄은 수식으로 취급 (Gemini가 변환한 LaTeX)
    lines = stripped.split('\n')
    eq_lines = []
    prose_lines = []
    for line in lines:
        ls = line.strip()
        if not ls:
            continue
        has_latex = bool(re.search(r'\\[a-zA-Z]', ls))
        english_words = re.findall(r'\b[a-z]{4,}\b', ls)
        math_ops = re.findall(r'[=+\-×÷≈≠≤≥∑∫∂]', ls)
        korean = re.findall(r'[가-힣]', ls)
        # 한국어가 있거나 (LaTeX 없이 영어 단어만 많으면) 산문
        if korean or (len(english_words) >= 4 and not has_latex and not math_ops):
            prose_lines.append(ls)
        else:
            if not prose_lines:
                eq_lines.append(ls)
            else:
                prose_lines.append(ls)

    # 수식 부분: 유니코드 → LaTeX 변환 (아직 변환 안 된 것 처리)
    eq_text = '\n'.join(eq_lines).strip()
    eq_text = _replace_unicode_math_in_math(eq_text)

    # 여러 줄 수식에 번호 태그가 있으면 align 환경으로 (equation은 단일 수식만)
    eq_raw_lines = [l for l in eq_text.split('\n') if l.strip()]
    numbered = re.findall(r',?\s*\((\d+)\)\s*$', eq_text, re.MULTILINE)
    if len(eq_raw_lines) > 1 and numbered:
        align_lines = []
        for line in eq_raw_lines:
            line = re.sub(r',?\s*\((\d+)\)\s*$', r' \\tag{\1}', line.strip())
            align_lines.append(line)
        result = "\\begin{align}\n" + " \\\\\n".join(align_lines) + "\n\\end{align}"
    else:
        result = f"\\begin{{equation}}\n{eq_text}\n\\end{{equation}}"

    # 산문 부분: 텍스트로 출력
    if prose_lines:
        prose = ' '.join(prose_lines)
        prose = prose.replace('ﬁ', 'fi').replace('ﬂ', 'fl')
        result += '\n\n' + escape_latex_text(_replace_unicode_math(prose))

    return result


def format_figure(caption: str, fig_path: str, fig_num: int) -> str:
    """그림 환경을 생성한다. 파일이 없으면 플레이스홀더."""
    # "그림 N:" 또는 "Figure N:" 접두사 중복 방지
    caption = re.sub(r'^(그림|Figure|FIG\.?)\s*\d+\s*[:.]\s*', '', caption, flags=re.IGNORECASE).strip()
    escaped_caption = escape_latex_text(caption)
    if os.path.exists(fig_path):
        rel_path = "figures/" + os.path.basename(fig_path)
        image_content = f"  \\includegraphics[width=0.9\\textwidth]{{{rel_path}}}"
    else:
        image_content = (
            "  \\fbox{\\parbox{0.9\\textwidth}{\\centering "
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


def validate_latex(tex: str) -> list:
    """LaTeX 구조를 검증하고 오류 목록을 반환한다."""
    errors = []

    # $ 짝 확인 (\\$ 이스케이프 제외)
    dollar_count = len(re.findall(r'(?<!\\)\$', tex))
    if dollar_count % 2 != 0:
        errors.append(f"홀수 개의 $ 발견 ({dollar_count}개) — 수식 구분자 짝이 맞지 않습니다.")

    # \begin / \end 짝 확인 (환경 이름 기준)
    begins = re.findall(r'\\begin\{(\w+\*?)\}', tex)
    ends = re.findall(r'\\end\{(\w+\*?)\}', tex)
    if sorted(begins) != sorted(ends):
        errors.append(f"\\begin과 \\end 짝 불일치: begins={begins}, ends={ends}")

    # {} 균형 확인 (이스케이프된 \{ \} 제외)
    depth = 0
    i = 0
    while i < len(tex):
        if tex[i] == '\\' and i + 1 < len(tex) and tex[i + 1] in ('\\', '{', '}'):
            i += 2  # 이스케이프된 문자 건너뜀
            continue
        if tex[i] == '{':
            depth += 1
        elif tex[i] == '}':
            depth -= 1
            if depth < 0:
                errors.append("닫는 } 가 여는 { 보다 많습니다.")
                depth = 0
        i += 1
    if depth != 0:
        errors.append(f"여는 {{ 가 닫히지 않았습니다 (미닫힌 깊이: {depth}).")

    return errors


def build_latex(
    translated_blocks: list,
    config: dict,
    output_dir: str,
    figures_dir: str,
    source_pdf_path: str = "",
) -> tuple:
    """번역된 블록으로 .tex 파일을 생성한다. (tex_path, errors) 반환."""
    latex_cfg = config.get("latex", {})
    documentclass = latex_cfg.get("documentclass", "article")
    font_main = latex_cfg.get("font_main", "NanumMyeongjo")
    font_sans = latex_cfg.get("font_sans", "NanumGothic")

    # 블록 분류
    title_text = ""
    authors_text = ""
    abstract_text = ""
    body_blocks = []
    reference_blocks = []

    for block in translated_blocks:
        t = block.get("translated_text") or block["text"]
        btype = block["type"]
        if btype == "title":
            title_text = t
        elif btype == "authors":
            authors_text = t
        elif btype == "abstract":
            abstract_text = t
        elif btype == "reference":
            reference_blocks.append(block)
        else:
            body_blocks.append(block)

    # abstract가 감지되지 않은 경우 — 첫 번째 긴 paragraph를 fallback으로 사용
    if not abstract_text and body_blocks:
        for i, blk in enumerate(body_blocks):
            t = blk.get("translated_text") or blk["text"]
            if blk["type"] == "paragraph" and len(t) > 150:
                abstract_text = t
                body_blocks.pop(i)
                break

    two_column = latex_cfg.get("two_column", False)

    tex = build_preamble(documentclass, font_main, font_sans, latex_cfg)
    tex += f"\\title{{{escape_latex(title_text)}}}\n"
    tex += f"\\author{{{escape_latex(authors_text)}}}\n"
    tex += "\\date{\\today}\n\n"
    tex += "\\begin{document}\n"
    tex += "\\maketitle\n\n"

    if abstract_text:
        tex += "\\begin{abstract}\n"
        tex += escape_latex_text(fix_gemini_latex(strip_control_chars(abstract_text))) + "\n"
        tex += "\\end{abstract}\n\n"

    # 2단 조판 시작 (제목/초록은 전체 폭, 본문부터 2단)
    if two_column:
        tex += "\\begin{multicols}{2}\n\n"

    fig_counter = [0]

    i = 0
    while i < len(body_blocks):
        block = body_blocks[i]
        text = block.get("translated_text") or block["text"]
        btype = block["type"]

        if btype == "section":
            tex += f"\n\\section{{{escape_latex(text)}}}\n\n"
        elif btype == "subsection":
            tex += f"\n\\subsection{{{escape_latex(text)}}}\n\n"
        elif btype == "paragraph":
            tex += escape_latex_text(fix_gemini_latex(strip_control_chars(text))) + "\n\n"
        elif btype == "equation":
            eq_text = block.get("translated_text") or block["text"]
            tex += format_equation(strip_control_chars(eq_text)) + "\n\n"
        elif btype == "caption":
            fig_counter[0] += 1
            fig_path = os.path.join(figures_dir, f"fig_{fig_counter[0]:03d}.png")
            tex += format_figure(fix_gemini_latex(strip_control_chars(text)), fig_path, fig_counter[0]) + "\n\n"
        elif btype == "table_caption":
            j = i + 1
            data_blks = []
            while j < len(body_blocks) and body_blocks[j]["type"] == "table_data":
                data_blks.append(body_blocks[j])
                j += 1
            tex += format_table(text, data_blks) + "\n\n"
            i = j
            continue
        elif btype == "table_data":
            pass  # table_caption에서 처리됨
        i += 1

    if two_column:
        tex += "\\end{multicols}\n\n"

    if reference_blocks:
        # 참고문헌도 2단으로 (저널 논문 스타일)
        if two_column:
            tex += "\\begin{multicols}{2}\n"
        tex += "\\begin{thebibliography}{99}\n"
        ref_num = 1
        for ref in reference_blocks:
            items = re.split(r'(?=\[\d+\])', ref['text'].strip())
            for item in items:
                item = item.strip()
                if not item:
                    continue
                item = re.sub(r'^\[\d+\]\s*', '', item).strip()
                if item:
                    tex += f"\\bibitem{{ref{ref_num}}} {escape_latex(item)}\n\n"
                    ref_num += 1
        tex += "\\end{thebibliography}\n"
        if two_column:
            tex += "\\end{multicols}\n"

    tex += "\n\\end{document}\n"

    errors = validate_latex(tex)

    os.makedirs(output_dir, exist_ok=True)
    if source_pdf_path:
        base = os.path.splitext(os.path.basename(source_pdf_path))[0]
        tex_name = base + "_번역.tex"
    else:
        tex_name = "translated.tex"
    tex_path = os.path.join(output_dir, tex_name)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)

    return tex_path, errors
