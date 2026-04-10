# TRD — Physics-Trans v2.0
## 기술 설계 문서

**버전**: 2.0  
**작성일**: 2026-04-10  
**기반**: PRD v2.0, 레거시 코드 분석 결과

---

## 1. 시스템 아키텍처

```
paper.pdf
    │
    ▼
┌─────────────┐     paper.json
│ extractor.py│ ──────────────────►┐
└─────────────┘                    │
                                   ▼
                         ┌──────────────────┐     translated.json
                         │  translator.py   │ ──────────────────►┐
                         └──────────────────┘                    │
                                                                  ▼
                                                       ┌──────────────────┐
                                                       │   composer.py    │
                                                       └──────────────────┘
                                                                  │
                                              ┌───────────────────┼──────────────────┐
                                              ▼                   ▼                  ▼
                                        paper_번역.tex    figures/fig_001.png   paper_번역.pdf

공통 유틸리티: utils.py (수식 보호, 용어사전, LaTeX 이스케이프, Gemini 출력 교정)
설정: config.yaml
진입점: main.py
```

---

## 2. 폴더 구조

```
physics-trans/
├── main.py                  # CLI 진입점
├── extractor.py             # PDF → JSON
├── translator.py            # JSON → 번역 JSON
├── composer.py              # JSON → .tex → .pdf
├── utils.py                 # 공통 유틸리티
├── config.yaml              # 설정 파일
├── template.tex.j2          # Jinja2 LaTeX 템플릿
├── requirements.txt
├── .gitignore               # credentials, .env 포함
├── legacy/                  # 구 코드 (참고용, 수정 금지)
│   ├── pdf_parser.py
│   ├── translator.py
│   ├── latex_builder.py
│   └── compiler.py
├── output/                  # 생성 파일 출력 디렉토리
│   ├── figures/             # 추출된 그림 PNG
│   └── translated_blocks.json  # 번역 캐시
└── tests/
    └── test_paper.pdf       # 테스트용 논문
```

---

## 3. 데이터 규격 (JSON)

### 3.1 paper.json (extractor 출력)

```json
{
  "metadata": {
    "title": "Laser cooling and trapping of neutral atoms",
    "authors": "Adams, C. S. and Riis, E.",
    "pages": 12,
    "source_pdf": "adams_riis_1997.pdf"
  },
  "blocks": [
    {
      "id": "block_001",
      "type": "abstract",
      "text": "We review the...",
      "page": 1,
      "bbox": [50.0, 100.0, 400.0, 150.0]
    },
    {
      "id": "block_042",
      "type": "equation",
      "text": "$F = ma$",
      "page": 3,
      "bbox": [200.0, 300.0, 350.0, 320.0],
      "equation_number": "(2.1)"
    },
    {
      "id": "block_055",
      "type": "figure_caption",
      "text": "Fig. 1. Schematic diagram of...",
      "page": 4,
      "bbox": [50.0, 600.0, 400.0, 630.0],
      "figure_index": 1,
      "figure_path": "output/figures/fig_001.png"
    }
  ],
  "figures": [
    {
      "index": 1,
      "path": "output/figures/fig_001.png",
      "page": 4,
      "bbox": [50.0, 400.0, 400.0, 595.0]
    }
  ]
}
```

**블록 타입 목록**:

| 타입 | 설명 |
|------|------|
| `title` | 논문 제목 |
| `authors` | 저자 정보 |
| `abstract` | 초록 |
| `section` | 섹션 헤더 (1. Introduction) |
| `subsection` | 서브섹션 헤더 (1.1 Background) |
| `paragraph` | 본문 단락 |
| `equation` | 수식 블록 |
| `figure_caption` | 그림 캡션 |
| `table_caption` | 표 캡션 |
| `table_data` | 표 데이터 |
| `reference` | 참고문헌 항목 |

### 3.2 translated.json (translator 출력)

```json
{
  "metadata": { "...paper.json 동일..." },
  "blocks": [
    {
      "id": "block_001",
      "type": "abstract",
      "text": "We review the...",
      "translated_text": "본 논문에서는...",
      "page": 1,
      "bbox": [50.0, 100.0, 400.0, 150.0]
    }
  ],
  "figures": [ "...paper.json 동일..." ]
}
```

---

## 4. 모듈별 설계

### 4.1 extractor.py

**역할**: PDF → paper.json

**의존성**: `pymupdf4llm`, `fitz` (PyMuPDF)

**주요 함수**:

```python
def extract(pdf_path: str) -> dict:
    """
    PDF를 파싱하여 paper.json 형태의 dict 반환.
    내부적으로 3패스 실행:
      1패스: 텍스트 블록 수집 + 분류
      2패스: 수식/표 후처리
      3패스: 그림 PNG 추출
    """

def _classify_block(block: dict, page_num: int) -> str:
    """블록 타입 분류. 레거시 classify_block() 로직 이식."""

def _extract_figures(doc, blocks: list) -> list:
    """
    캡션 위치 기반 그림 영역 계산 후 PNG 저장.
    레거시 _render_figures() 로직 이식.
    저장 경로: output/figures/fig_{N:03d}.png
    반환: figures 리스트 (index, path, page, bbox)
    """

def _merge_hyphenated(blocks: list) -> list:
    """하이픈 줄바꿈 병합. 레거시 로직 이식."""
```

**레거시에서 이식할 로직**:
- `classify_block()` 분류 규칙 (타입 판별 조건 그대로)
- `_render_figures()` 캡션 bbox 기반 그림 영역 계산
- `_merge_adjacent_equations()` 연속 수식 병합
- 하이픈 줄바꿈 병합 로직

---

### 4.2 translator.py

**역할**: paper.json → translated.json

**의존성**: `google-cloud-aiplatform`, `vertexai`

**인증**: gcloud ADC (`GOOGLE_APPLICATION_CREDENTIALS` 또는 `gcloud auth application-default login`)

**주요 함수**:

```python
def translate(paper: dict, config: dict) -> dict:
    """
    paper.json을 받아 각 블록을 번역.
    equation 타입은 번역 건너뜀 (원문 유지).
    reference 타입은 번역 건너뜀 (원문 유지).
    캐시 적중 시 API 호출 생략.
    """

def _translate_block(block: dict, model: GenerativeModel, config: dict) -> str:
    """
    단일 블록 번역.
    1. utils.protect_equations(text) 호출
    2. Vertex AI API 호출
    3. utils.restore_equations(result) 호출
    4. 환각 감지: 결과 길이 > 원문 3배 → 재시도
    5. 수식 개수 불일치 → 재시도
    """

def _build_system_prompt(style: str) -> str:
    """번역 시스템 프롬프트 생성. style: '합니다체' | '해요체'"""

def _load_cache(cache_path: str) -> dict:
def _save_cache(cache: dict, cache_path: str) -> None:
```

**Vertex AI 연동**:

```python
import vertexai
from vertexai.generative_models import GenerativeModel

vertexai.init(project=config["project_id"], location=config["location"])

# system_instruction은 모델 초기화 시 한 번만 설정 (블록마다 재생성 금지)
model = GenerativeModel(
    "gemini-3.0-flash",
    system_instruction=system_prompt,
)
# 사용자 메시지만 generate_content에 전달
response = model.generate_content(user_prompt)
```

**환각 감지 조건** (둘 중 하나라도 해당 시 재시도):
1. `len(translated) > len(original) * 3`
2. `translated.count("__EQ") != original.count("__EQ")` (플레이스홀더 소실)

**재시도**: 지수 백오프, 최대 3회. 최종 실패 시 원문 반환.

**병렬 처리**: `ThreadPoolExecutor(max_workers=5)`

---

### 4.3 composer.py

**역할**: translated.json → .tex → .pdf

**의존성**: `jinja2`, `subprocess` (XeLaTeX)

**주요 함수**:

```python
def compose(translated: dict, config: dict) -> str:
    """
    translated.json을 받아 .tex 생성 후 XeLaTeX 컴파일.
    반환: 생성된 PDF 경로
    """

def _render_template(translated: dict, config: dict) -> str:
    """
    Jinja2로 template.tex.j2에 데이터 주입.
    반환: .tex 파일 내용 문자열
    """

def _compile(tex_path: str, config: dict) -> tuple[bool, str]:
    """
    XeLaTeX 2회 컴파일.
    반환: (성공여부, 오류메시지)
    """

def _validate_latex(tex_content: str) -> list[str]:
    """
    $ 짝, {} 깊이, \begin/\end 짝 검증.
    반환: 오류 목록 (빈 리스트 = 정상)
    """
```

**template.tex.j2 구조**:

```latex
\documentclass[reprint,aps,prl]{revtex4-2}
\usepackage{fontspec}
\usepackage{kotex}
\setmainfont{NanumMyeongjo}
\usepackage{amsmath,amssymb,graphicx,float,hyperref,booktabs}

\begin{document}

\title{ {{ metadata.title }} }
\author{ {{ metadata.authors }} }
\begin{abstract}
{{ abstract_text }}
\end{abstract}
\maketitle

{% for block in body_blocks %}
  {% if block.type == 'section' %}
\section{ {{ block.translated_text }} }
  {% elif block.type == 'paragraph' %}
{{ block.translated_text }}

  {% elif block.type == 'equation' %}
{{ block.text | format_equation }}
  {% elif block.type == 'figure_caption' %}
{{ block | format_figure }}
  {% endif %}
{% endfor %}

\begin{thebibliography}{99}
{% for ref in reference_blocks %}
\bibitem{} {{ ref.text }}
{% endfor %}
\end{thebibliography}

\end{document}
```

---

### 4.4 utils.py

**역할**: 공통 유틸리티 (모든 모듈에서 import)

**함수 목록**:

```python
# 수식 보호/복원 (레거시에서 이식, 단일 정의)
def protect_equations(text: str) -> tuple[str, dict]:
    """
    수식을 __EQ0__, __EQ1__, ... 로 치환.
    치환 순서: $$ → \begin{equation} → $
    반환: (보호된 텍스트, {플레이스홀더: 원본수식} 매핑)
    """

def restore_equations(text: str, mapping: dict) -> str:
    """플레이스홀더를 원본 수식으로 복원."""

# Gemini 출력 교정 (레거시 fix_gemini_latex() 이식)
def fix_gemini_latex(text: str) -> str:
    """
    Gemini가 잘못 생성한 LaTeX 패턴 교정:
    - \sqrt 5 → \sqrt{5}
    - \text{} 안의 수학 명령어 이동
    - bare LaTeX 명령어 → $...$ 감싸기
    """

# LaTeX 특수문자 이스케이프
def escape_latex(text: str) -> str:
    """%, &, #, _, ^, ~ 등 이스케이프."""

# 물리학 용어 사전
TERM_DICT = {
    "laser cooling": "레이저 냉각",
    "trapping": "포획",
    "magneto-optical trap": "자기광학 포획기",
    "Doppler cooling": "도플러 냉각",
    "recoil limit": "반동 한계",
    # ... 확장 가능
}

def apply_term_dict(text: str) -> str:
    """번역 후 용어 사전 기반 용어 통일 적용."""
```

---

### 4.5 config.yaml

```yaml
# Vertex AI
project_id: "your-gcp-project-id"
location: "us-central1"
model: "gemini-3.0-flash"

# 번역 설정
translation_style: "합니다체"
max_workers: 5
max_retries: 3
hallucination_ratio: 3.0

# LaTeX 설정
document_class: "revtex4-2"
main_font: "NanumMyeongjo"
sans_font: "Malgun Gothic"

# 경로
output_dir: "output"
figures_dir: "output/figures"
cache_file: "output/translated_blocks.json"
template_file: "template.tex.j2"
```

---

## 5. main.py (진입점)

```python
import sys
import yaml
from extractor import extract
from translator import translate
from composer import compose

def main(pdf_path: str):
    config = yaml.safe_load(open("config.yaml"))

    print("[1/3] 추출 중...")
    paper = extract(pdf_path)
    print(f"      ✓ {paper['metadata']['pages']}페이지, "
          f"{len(paper['figures'])}개 그림 감지")

    print("[2/3] 번역 중...")
    translated = translate(paper, config)

    print("[3/3] 조립 중...")
    pdf_path_out = compose(translated, config)
    print(f"\n→ {pdf_path_out}")

if __name__ == "__main__":
    main(sys.argv[1])
```

---

## 6. 레거시 이식 지침

| 레거시 함수 | 이식 대상 | 비고 |
|-------------|-----------|------|
| `classify_block()` | `extractor.py` | 분류 조건 그대로 이식 |
| `_render_figures()` | `extractor.py` | 캡션 bbox 로직 이식 |
| `_merge_adjacent_equations()` | `extractor.py` | 그대로 이식 |
| 하이픈 병합 로직 | `extractor.py` | 그대로 이식 |
| `protect_equations()` (translator.py 버전) | `utils.py` | 단일 정의로 통합 |
| `restore_equations()` | `utils.py` | 단일 정의로 통합 |
| `fix_gemini_latex()` | `utils.py` | 그대로 이식 |
| `validate_latex()` | `composer.py` | 그대로 이식 |
| `compile_latex()` | `composer.py` | 그대로 이식 |
| `pdf_parser.py의 protect_equations_in_text()` | **삭제** | dead code |

---

## 7. 구현 순서 (Claude Code 작업 순서)

```
1단계: 뼈대
  └─ config.yaml 작성
  └─ utils.py 작성 (protect/restore/fix_gemini_latex/escape_latex)
  └─ main.py 뼈대 작성

2단계: extractor.py
  └─ 레거시 로직 이식
  └─ paper.json 출력 테스트 (테스트 논문 1편)

3단계: translator.py
  └─ Vertex AI ADC 연결 테스트
  └─ 단일 블록 번역 테스트
  └─ 캐시 + 병렬 처리 추가

4단계: composer.py
  └─ template.tex.j2 작성
  └─ Jinja2 렌더링 테스트
  └─ XeLaTeX 컴파일 테스트

5단계: 통합 테스트
  └─ Adams & Riis (1997) 전체 실행
  └─ 결과물 품질 검증
```

---

## 8. 미해결 과제 (레거시에서 이월)

| ID | 문제 | 우선순위 |
|----|------|----------|
| A | `_fix_orphan_radicands()` 블록 내부 인라인 √ 미처리 | 중 |
| B | radicand 제거 후 남는 구두점 파편 | 하 |
| C | multi-token 하이픈 파편 ("ence of") 미처리 | 중 |
| D | ~적으로. 단락 파편 필터 없음 | 하 |
| E | "Cases." 같은 단독 섹션 레이블 필터 없음 | 하 |
| F | 표 두 열 분리 문제 | 중 |
| G | 전면 배치 그림(single-column spanning figure) 처리 | 중 |

**v2.0 범위**: A, C, G 해결 목표. B, D, E, F는 v2.1로 이월.

