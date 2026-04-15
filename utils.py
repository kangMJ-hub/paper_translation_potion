"""
utils.py — Physics-Trans v2.0 공통 유틸리티
모든 모듈에서 import하여 사용.
"""

import re


# ---------------------------------------------------------------------------
# 수식 보호 / 복원
# ---------------------------------------------------------------------------

def protect_equations(text: str) -> tuple[str, dict]:
    """
    수식을 __EQ0__, __EQ1__, ... 플레이스홀더로 치환한다.
    치환 순서: $$ → \\begin{equation} → $  (순서 중요)
    반환: (보호된 텍스트, {플레이스홀더: 원본수식} 매핑)
    """
    mapping: dict[str, str] = {}
    counter = [0]

    def replace_match(match: re.Match) -> str:
        key = f"__EQ{counter[0]}__"
        mapping[key] = match.group(0)
        counter[0] += 1
        return key

    # 1) display math: $$...$$
    text = re.sub(r'\$\$.*?\$\$', replace_match, text, flags=re.DOTALL)
    # 2) equation 환경: \begin{equation}...\end{equation}
    text = re.sub(
        r'\\begin\{equation\}.*?\\end\{equation\}',
        replace_match, text, flags=re.DOTALL
    )
    # 3) inline math: $...$
    text = re.sub(r'\$[^$\n]+?\$', replace_match, text)

    return text, mapping


def restore_equations(text: str, mapping: dict) -> str:
    """플레이스홀더를 원본 수식으로 복원한다."""
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


# ---------------------------------------------------------------------------
# Gemini 출력 LaTeX 교정
# ---------------------------------------------------------------------------

def _fix_text_block(m: re.Match) -> str:
    """\\text{} 안의 LaTeX 수학 명령어를 밖으로 꺼낸다."""
    inner = m.group(1)
    if not re.search(r'\\[a-zA-Z]+', inner):
        return m.group(0)
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


def fix_gemini_latex(text: str) -> str:
    """
    Gemini가 잘못 생성한 LaTeX 패턴을 교정한다:
    - \\sqrt 5 → \\sqrt{5}
    - \\text{} 안의 수학 명령어 밖으로 이동
    - \\mathcal{소문자 명령어} 제거
    - bare LaTeX 명령어($ 없는 줄) → $...$ 로 감싸기
    """
    # \mathcal{소문자 명령어} 정리
    text = re.sub(r'\$\\mathcal\{(\\[a-z]+)\}\$', r'$\1$', text)
    text = re.sub(r'\\mathcal\{(\\[a-z]+)\}', r'\1', text)

    # \sqrt 뒤 공백+내용 → \sqrt{내용}  (빈 \sqrt{} 는 건드리지 않음)
    text = re.sub(r'\\sqrt\s+(\S)', r'\\sqrt{\1}', text)

    # \text{} 안 수학 명령어 밖으로
    text = re.sub(r'\\text\{([^}]*\\[a-zA-Z]+[^}]*)\}', _fix_text_block, text)

    # bare LaTeX 명령어 줄 → $...$ 감싸기
    lines = text.split('\n')
    wrapped = []
    for line in lines:
        stripped = line.strip()
        if '$' in stripped or '\\begin{' in stripped:
            wrapped.append(line)
            continue
        latex_cmds = re.findall(r'\\[a-zA-Z]+', stripped)
        korean = re.findall(r'[가-힣]', stripped)
        if len(latex_cmds) >= 2 and not korean and len(stripped) < 300:
            wrapped.append(f'${stripped}$')
        else:
            wrapped.append(line)
    return '\n'.join(wrapped)


# ---------------------------------------------------------------------------
# Unicode 수식 기호 → LaTeX 명령어 변환
# ---------------------------------------------------------------------------

_UNICODE_MATH_MAP: list[tuple[str, str]] = [
    # 그리스 소문자
    ("α", r"\alpha"),   ("β", r"\beta"),    ("γ", r"\gamma"),   ("δ", r"\delta"),
    ("ε", r"\varepsilon"), ("ǫ", r"\varepsilon"), ("ζ", r"\zeta"), ("η", r"\eta"),
    ("θ", r"\theta"),   ("ι", r"\iota"),    ("κ", r"\kappa"),   ("λ", r"\lambda"),
    ("μ", r"\mu"),      ("ν", r"\nu"),      ("ξ", r"\xi"),      ("π", r"\pi"),
    ("ρ", r"\rho"),     ("σ", r"\sigma"),   ("τ", r"\tau"),     ("υ", r"\upsilon"),
    ("φ", r"\phi"),     ("χ", r"\chi"),     ("ψ", r"\psi"),     ("ω", r"\omega"),
    # 그리스 대문자
    ("Γ", r"\Gamma"),   ("Δ", r"\Delta"),   ("Θ", r"\Theta"),   ("Λ", r"\Lambda"),
    ("Ξ", r"\Xi"),      ("Π", r"\Pi"),      ("Σ", r"\Sigma"),   ("Υ", r"\Upsilon"),
    ("Φ", r"\Phi"),     ("Ψ", r"\Psi"),     ("Ω", r"\Omega"),
    # 수학 기호
    ("≈", r"\approx"),  ("≠", r"\neq"),     ("≤", r"\leq"),     ("≥", r"\geq"),
    ("∞", r"\infty"),   ("∂", r"\partial"), ("∇", r"\nabla"),   ("∑", r"\sum"),
    ("∫", r"\int"),     ("∏", r"\prod"),    ("√", r"\sqrt"),    ("∼", r"\sim"),
    ("×", r"\times"),   ("÷", r"\div"),     ("±", r"\pm"),      ("∓", r"\mp"),
    ("·", r"\cdot"),    ("→", r"\to"),      ("←", r"\leftarrow"), ("↔", r"\leftrightarrow"),
    ("⟨", r"\langle"),  ("⟩", r"\rangle"),  ("†", r"\dagger"),  ("‡", r"\ddagger"),
    ("∝", r"\propto"),  ("∈", r"\in"),      ("∉", r"\notin"),   ("⊂", r"\subset"),
    ("∪", r"\cup"),     ("∩", r"\cap"),     ("∧", r"\wedge"),   ("∨", r"\vee"),
    # 폰트 미지원 문자 (Un Batang 등에서 빈 네모로 표시됨)
    ("−", r"-"),        ("◦", r"^\circ"),   ("∆", r"\Delta"),
    # 상첨자/하첨자
    ("⁰", r"^{0}"), ("¹", r"^{1}"), ("²", r"^{2}"), ("³", r"^{3}"),
    ("⁴", r"^{4}"), ("⁵", r"^{5}"), ("⁶", r"^{6}"), ("⁷", r"^{7}"),
    ("⁸", r"^{8}"), ("⁹", r"^{9}"), ("⁻", r"^{-}"), ("⁺", r"^{+}"),
    ("₀", r"_{0}"), ("₁", r"_{1}"), ("₂", r"_{2}"), ("₃", r"_{3}"),
]


def unicode_math_to_latex(text: str) -> str:
    """
    수식 텍스트 내 Unicode 수학 기호를 LaTeX 명령어로 변환한다.
    equation/align 블록에 적용하여 XeLaTeX 컴파일 오류를 방지한다.
    """
    for uni, latex in _UNICODE_MATH_MAP:
        text = text.replace(uni, latex)
    # ˆX → \hat{X}  (U+02C6 modifier circumflex + 다음 비공백 문자)
    text = re.sub(r"ˆ\s*(\S)", r"\\hat{\1}", text)
    # 나머지 고립된 ˆ 제거
    text = text.replace("ˆ", "")
    return text


def unicode_math_to_inline_latex(text: str) -> str:
    """본문 텍스트의 Unicode 수식 기호를 인라인 $...$ LaTeX로 변환한다."""
    # √ 는 뒤따르는 숫자/영문 인자만 포함해서 변환 (√5 → $\sqrt{5}$, 한글은 제외)
    text = re.sub(r"√([0-9a-zA-Z]+)", r"$\\sqrt{\1}$", text)
    text = text.replace("√", "$\\sqrt{}$")
    # 나머지 Unicode 수식 기호 변환 (√ 제외)
    for uni, latex_cmd in _UNICODE_MATH_MAP:
        if uni == "√":
            continue
        text = text.replace(uni, f"${latex_cmd}$")
    # ˆX → $\hat{X}$
    text = re.sub(r"ˆ\s*(\S)", r"$\\hat{\1}$", text)
    text = text.replace("ˆ", "")
    # ⃗ (U+20D7, combining right arrow above) → \vec{X}
    text = re.sub(r"(\S)\u20d7", r"$\\vec{\1}$", text)
    text = re.sub(r"\u20d7(\S)", r"$\\vec{\1}$", text)
    text = text.replace("\u20d7", "")  # 나머지 고립된 ⃗ 제거
    return text


# ---------------------------------------------------------------------------
# LaTeX 특수문자 이스케이프
# ---------------------------------------------------------------------------

def escape_latex(text: str) -> str:
    """
    LaTeX 특수문자를 이스케이프한다 (수식 모드 밖 전용).
    백슬래시를 가장 먼저 처리해야 이중 이스케이프가 발생하지 않는다.
    """
    # PDF 추출 합자(ligature) → 일반 문자로 변환
    text = (text.replace("ﬁ", "fi").replace("ﬂ", "fl")
                .replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬄ", "ffl"))
    text = text.replace("\\", "\\textbackslash{}")
    text = text.replace("%", "\\%")
    text = text.replace("&", "\\&")
    text = text.replace("#", "\\#")
    text = text.replace("_", "\\_")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("^", "\\^{}")
    text = text.replace("~", "\\textasciitilde{}")
    text = text.replace("$", "\\$")
    return text


# ---------------------------------------------------------------------------
# 물리학 용어 사전
# ---------------------------------------------------------------------------

TERM_DICT: dict[str, str] = {
    "laser cooling": "레이저 냉각",
    "laser trapping": "레이저 포획",
    "trapping": "포획",
    "magneto-optical trap": "자기광학 포획기",
    "MOT": "자기광학 포획기(MOT)",
    "Doppler cooling": "도플러 냉각",
    "Doppler limit": "도플러 한계",
    "recoil limit": "반동 한계",
    "recoil energy": "반동 에너지",
    "optical molasses": "광학 당밀",
    "radiation pressure": "복사 압력",
    "photon recoil": "광자 반동",
    "spontaneous emission": "자발 방출",
    "stimulated emission": "유도 방출",
    "absorption": "흡수",
    "scattering rate": "산란률",
    "detuning": "이탈 주파수",
    "saturation parameter": "포화 매개변수",
    "standing wave": "정재파",
    "traveling wave": "진행파",
    "dipole force": "쌍극자 힘",
    "dipole trap": "쌍극자 포획기",
    "optical lattice": "광학 격자",
    "Zeeman slower": "지만 감속기",
    "Zeeman effect": "지만 효과",
    "hyperfine structure": "초미세 구조",
    "fine structure": "미세 구조",
    "ground state": "바닥 상태",
    "excited state": "들뜬 상태",
    "transition frequency": "전이 주파수",
    "linewidth": "선폭",
    "natural linewidth": "자연 선폭",
    "coherence": "결맞음",
    "coherent": "결맞는",
    "incoherent": "결맞지 않는",
    "Bose-Einstein condensation": "보스-아인슈타인 응축",
    "BEC": "보스-아인슈타인 응축(BEC)",
    "evaporative cooling": "증발 냉각",
    "sub-Doppler cooling": "도플러 이하 냉각",
    "Sisyphus cooling": "시지프스 냉각",
    "polarization gradient cooling": "편광 기울기 냉각",
    "atom interferometry": "원자 간섭계",
    "atomic fountain": "원자 분수",
    "optical pumping": "광 펌핑",
    "dark state": "암흑 상태",
    "coherent population trapping": "결맞음 집단 포획",
    "CPT": "결맞음 집단 포획(CPT)",
    "electromagnetically induced transparency": "전자기 유도 투명도",
    "EIT": "전자기 유도 투명도(EIT)",
    "Hamiltonian": "해밀토니안",
    "wave function": "파동 함수",
    "density matrix": "밀도 행렬",
    "Bloch equations": "블로흐 방정식",
    "Rabi frequency": "라비 주파수",
    "Rabi oscillation": "라비 진동",
    "narrow pitch": "미세 피치",
    "narrow-pitch": "미세 피치",
}


def apply_term_dict(text: str) -> str:
    """번역 후 용어 사전 기반 물리학 용어를 통일한다 (대소문자 구분)."""
    for eng, kor in TERM_DICT.items():
        text = text.replace(eng, kor)
    return text


# ---------------------------------------------------------------------------
# Bare LaTeX 패턴 → $...$ 자동 감싸기
# ---------------------------------------------------------------------------

_BARE_LATEX_CMDS = re.compile(
    r"(?<!\w)"
    r"(\\(?:rightarrow|leftarrow|leftrightarrow|Rightarrow|Leftarrow|"
    r"to|cdot|times|pm|mp|approx|leq|geq|neq|infty|partial|nabla|"
    r"alpha|beta|gamma|delta|sigma|omega|mu|nu|lambda|pi|rho|tau|"
    r"phi|psi|theta|Gamma|Delta|Sigma|Omega|hbar|propto|sim|"
    r"circ|dagger|ln|exp|sin|cos|tan|log|hat|vec|bar|tilde|dot))"
    r"(?!\w)"
)

_BARE_SUBSUP = re.compile(
    r"(\\[a-zA-Z]+(?:[_^]\{(?:[^{}]|\{[^{}]*\})*\})+"  # \cmd_{...}^{...}
    r"|\w+(?:[_^]\{(?:[^{}]|\{[^{}]*\})*\})+)"           # word_{...}^{...}
)

# \frac{...}{...}, \sqrt{...} 등 인자형 bare 명령어 패턴 (\begin, \end 제외)
_BARE_CMD_ARGS = re.compile(
    r"(\\(?!begin\b|end\b)[a-zA-Z]+(?:\{(?:[^{}]|\{[^{}]*\})*\}){1,3})"
)


def wrap_bare_latex_in_text(text: str) -> str:
    """
    본문 텍스트에서 $...$로 감싸지지 않은 bare LaTeX 수식 패턴을 $...$로 감싼다.
    - subscript/superscript: word_{...}, word^{...}
    - 수학 명령어: \\rightarrow, \\pm 등
    이미 $...$ 안에 있는 내용은 건드리지 않는다.
    """
    _MATH_SPLIT = re.compile(r"(\$\$[^$]*?\$\$|\$[^$\n]+?\$)")

    def _process_plain(plain: str) -> str:
        # 1) 인자형 명령어(\frac{}{}, \sqrt{} 등) 먼저 감싸기 (내부 구조 보존)
        plain = _BARE_CMD_ARGS.sub(r"$\1$", plain)
        # 2) 새로 생긴 $...$ 보호 후 subscript/superscript 감싸기
        subparts = _MATH_SPLIT.split(plain)
        out = []
        for j, sp in enumerate(subparts):
            if j % 2 == 1:
                out.append(sp)  # 이미 수식: 그대로
            else:
                out.append(_BARE_SUBSUP.sub(r"$\1$", sp))
        plain = "".join(out)
        # 3) 새로 생긴 $...$ 보호 후 standalone 명령어 감싸기
        subparts = _MATH_SPLIT.split(plain)
        out = []
        for j, sp in enumerate(subparts):
            if j % 2 == 1:
                out.append(sp)  # 이미 수식: 그대로
            else:
                out.append(_BARE_LATEX_CMDS.sub(r"$\1$", sp))
        return "".join(out)

    parts = _MATH_SPLIT.split(text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)  # 기존 수식: 그대로
        else:
            result.append(_process_plain(part))
    return "".join(result)
