# TRD — Physics-Trans v2.0
## 기술 설계 문서

**버전**: 2.1
**작성일**: 2026-04-10 (최종 수정: 2026-04-15)
**기반**: PRD v2.1, 실제 구현 코드 기준

---

## 1. 시스템 아키텍처

```
paper.pdf
    │
    ▼
┌─────────────┐     paper.json
│ extractor.py│ ──────────────────►┐
└─────────────┘                    │
  ↑ 의존성:                        ▼
  Google Cloud Document AI   ┌──────────────────┐     translated.json
  DocLayout-YOLO             │  translator.py   │ ──────────────────►┐
  PyMuPDF (fitz)             └──────────────────┘                    │
                               ↑ 의존성:                             ▼
                               Vertex AI Gemini            ┌──────────────────┐
                                                           │   composer.py    │
                                                           └──────────────────┘
                                                                    │
                                         ┌──────────────────────────┼─────────────────┐
                                         ▼                          ▼                 ▼
                                   paper_번역.tex         figures/fig_001.png   paper_번역.pdf

공통 유틸리티: utils.py (수식 보호, 용어사전, LaTeX 이스케이프, Gemini 출력 교정)
설정: config.yaml
진입점: main.py
비교 뷰어: viewer.py (localhost:8765, 브라우저 기반)
```

---

## 2. 폴더 구조

```
physics-trans/
├── main.py                  # CLI 진입점
├── extractor.py             # PDF → JSON (DocAI + YOLO + PyMuPDF)
├── translator.py            # JSON → 번역 JSON (Vertex AI Gemini)
├── composer.py              # JSON → .tex → .pdf (Jinja2 + XeLaTeX)
├── utils.py                 # 공통 유틸리티
├── viewer.py                # 원본/번역본 브라우저 비교 뷰어
├── config.yaml              # 설정 파일
├── template.tex.j2          # Jinja2 LaTeX 템플릿
├── requirements.txt
├── .gitignore               # credentials, .env 포함
├── legacy/                  # 구 코드 (참고용, 수정 금지)
├── output/                  # 생성 파일 출력 디렉토리
│   ├── figures/             # 추출된 그림 PNG
│   └── translated_blocks.json  # 번역 캐시
└── test_paper/              # 테스트용 논문 PDF
```

---

## 3. 데이터 규격 (JSON)

### 3.1 paper.json (extractor 출력)

```json
{
  "metadata": {
    "title": "Reactive Ion Etching Challenges...",
    "authors": "S. Tahara",
    "pages": 2,
    "source_pdf": "한계 1.pdf",
    "layout": "twocolumn"
  },
  "blocks": [
    {
      "id": "block_0000",
      "type": "title",
      "text": "Reactive Ion Etching Challenges...",
      "page": 1,
      "bbox": []
    },
    {
      "id": "block_0010",
      "type": "figure_caption",
      "text": "Fig. 1. 3DNAND AR increase by generation.",
      "page": 1,
      "bbox": [],
      "figure_index": 1,
      "figure_path": "output/figures/fig_001.png"
    }
  ],
  "figures": [
    {
      "index": 1,
      "path": "output/figures/fig_001.png",
      "page": 1,
      "bbox": [50.0, 300.0, 280.0, 580.0]
    }
  ]
}
```

> **주의**: `bbox`는 DocAI Layout Parser가 document_layout 블록에 좌표를 제공하지 않으므로 모든 텍스트 블록에서 `[]`로 비어있음. `figures`의 bbox는 YOLO 탐지 결과(pt 단위).

**블록 타입 목록**:

| 타입 | 설명 |
|------|------|
| `title` | 논문 제목 (첫 번째 heading-1) |
| `authors` | 저자 정보 |
| `abstract` | 초록 |
| `section` | 섹션 헤더 |
| `subsection` | 서브섹션 헤더 |
| `paragraph` | 본문 단락 |
| `equation` | 수식 블록 |
| `figure_caption` | 그림 캡션 (figure_index, figure_path 포함) |
| `table_caption` | 표 캡션 |
| `table_data` | 표 데이터 |
| `reference` | 참고문헌 항목 |
| `figure` | 그림 영역 플레이스홀더 (텍스트 없음, composer에서 스킵) |

### 3.2 translated.json (translator 출력)

```json
{
  "metadata": { "...paper.json 동일..." },
  "blocks": [
    {
      "id": "block_0000",
      "type": "title",
      "text": "Reactive Ion Etching Challenges...",
      "translated_text": "메모리 소자 제작을 위한 반응성 이온 식각의 과제와 기술",
      "page": 1,
      "bbox": []
    }
  ],
  "figures": [ "...paper.json 동일..." ]
}
```

---

## 4. 모듈별 설계

### 4.1 extractor.py

**역할**: PDF → paper.json

**의존성**: `google-cloud-documentai`, `fitz` (PyMuPDF), `doclayout_yolo`, `vertexai` (Gemini Vision fallback)

**처리 단계**:

```
1단계: Google Cloud Document AI Layout Parser 호출
       → document_layout.blocks (계층 트리) 수신

2단계: 블록 변환 + 후처리
       _parse_blocks()     — DocAI 트리 → 플랫 블록 리스트
       _postprocess()      — 중복 제거, 반복 헤더 제거, 참고문헌 재분류,
                             단편 병합, 참고문헌 fallback

3단계: 그림 PNG 추출
       _extract_figures()  — 우선순위: visual_elements → YOLO → Gemini Vision
       YOLO 매핑: y좌표 오름차순 (Figure 번호 순서 = 페이지 위→아래)

4단계: 그림 내부 텍스트 제거
       _filter_figure_text_blocks()  — YOLO bbox + PyMuPDF 좌표 교차 검증
       ※ 래스터 이미지 내부 텍스트는 _classify_paragraph 동사 필터로 대응
```

**주요 함수**:

```python
def extract(pdf_path: str, config: dict) -> dict
def _call_documentai(...) -> documentai.Document
def _parse_blocks(document) -> list[dict]
def _classify_paragraph(text: str, position: int) -> str
def _postprocess(blocks: list[dict], pdf_path: str) -> list[dict]
def _merge_leading_fragments(blocks) -> list[dict]   # 컬럼 경계 단편 병합
def _fix_references_fallback(blocks, pdf_path) -> list[dict]  # 참고문헌 PyMuPDF fallback
def _extract_figures(...) -> tuple[list[dict], dict[int, list]]  # figures + yolo_bboxes 반환
def _best_yolo_bbox_for_caption(cap_page, yolo_bboxes, used) -> list[float]  # y좌표 기준
def _filter_figure_text_blocks(blocks, yolo_bboxes, pdf_path) -> list[dict]
def _detect_layout(pdf_path) -> str   # "twocolumn" | "onecolumn"
```

**_classify_paragraph 필터 계층**:

```
1. 숫자 단독 / arXiv / IEEE 저작권 등 → skip
2. 서브그림 레이블 "(a)..." → skip
3. SEM/TEM 메타데이터 패턴 → skip
4. 단편 필터 (len<80, 단어≤8, 동사 없음, 마침표 없음) → skip
5. 동사 없는 긴 기술 명사구 (len<200, 동사 없음, 콤마<2) → skip
6. OCR 쓰레기 (정상 문자 비율 <70%) → skip
7. 캡션 패턴 (Fig./Table + 번호) → figure_caption / table_caption
8. 참고문헌 패턴 ([N] / N)) → reference
9. Abstract / 수식 / 저자 → 각 타입
10. 그 외 → paragraph
```

---

### 4.2 translator.py

**역할**: paper.json → translated.json

**의존성**: `google-cloud-aiplatform`, `vertexai`

**인증**: gcloud ADC (`GOOGLE_APPLICATION_CREDENTIALS` 또는 `gcloud auth application-default login`)

**주요 함수**:

```python
def translate(paper: dict, config: dict) -> dict
def _translate_block(block: dict, model, config) -> str
def _normalize_equation(block: dict, model, config) -> str
def _build_system_prompt(style: str) -> str
def _load_cache(cache_path: str) -> dict
def _save_cache(cache: dict, cache_path: str) -> None
```

**블록별 처리**:

| 블록 타입 | 처리 |
|-----------|------|
| `equation` | LaTeX 정규화 (번역 아님, `_normalize_equation`) |
| `reference` | 원문 그대로 (`translated_text = text`) |
| 나머지 | Gemini 번역 (`_translate_block`) |

**`_translate_block` 처리 순서**:

```
1. protect_equations(text)  → (protected, eq_map)
2. Vertex AI API 호출 (system_instruction 포함)
3. restore_equations(translated, eq_map)
4. 환각 감지: len(translated) > len(text) * 3 → 재시도
5. fix_gemini_latex() → apply_term_dict()
6. 최종 실패 시 원문 반환
```

**환각 감지 조건**: 번역 결과 길이 > 원문 3배 → 재시도 (최대 3회)

**재시도**: API 권장 대기시간 파싱 + 지수 백오프

**병렬 처리**: `ThreadPoolExecutor(max_workers=5)`

**캐시**: 블록 ID 기반, 번역 실패(원문 반환, 한국어 없음) 시 캐시 미저장

---

### 4.3 composer.py

**역할**: translated.json → .tex → .pdf

**의존성**: `jinja2`, `subprocess` (XeLaTeX)

**주요 함수**:

```python
def compose(translated: dict, config: dict) -> str
def _render_template(translated: dict, config: dict) -> str
def _compile(tex_path: str, config: dict) -> tuple[bool, str]
def _validate_latex(tex: str) -> list[str]
def _escape_latex_text(text: str) -> str
def _filter_format_figure(block: dict) -> str
def _filter_format_equation(text: str) -> str
```

**컴파일 전략**:
- XeLaTeX 2회 실행 (cross-reference 해소)
- `returncode != 0`이라도 PDF가 생성됐으면 경고만 출력하고 진행 (bbl 없음 등 경미한 오류 대응)

**template.tex.j2 구조** (실제 사용 변수):

```
((( metadata.translated_title )))   ← 번역된 제목
((( metadata.authors )))
((( abstract_text )))               ← 이스케이프 처리된 초록
((*  for block in body_blocks  *))
  section / subsection / paragraph / equation / figure_caption / table
((*  endfor  *))
참고문헌: reference_blocks (번호 순 정렬)
```

---

### 4.4 utils.py

**역할**: 공통 유틸리티 (모든 모듈에서 import)

**함수 목록**:

```python
# 수식 보호/복원
def protect_equations(text: str) -> tuple[str, dict]:
    """치환 순서: $$ → \begin{equation} → $"""

def restore_equations(text: str, mapping: dict) -> str

# Gemini 출력 교정
def fix_gemini_latex(text: str) -> str
def wrap_bare_latex_in_text(text: str) -> str
def unicode_math_to_inline_latex(text: str) -> str

# LaTeX 특수문자 이스케이프
def escape_latex(text: str) -> str

# 물리학 용어 사전
TERM_DICT: dict[str, str]
def apply_term_dict(text: str) -> str
```

---

### 4.5 config.yaml

```yaml
# Google Cloud
project_id: "your-gcp-project-id"
docai_location: "us"
docai_processor_id: "your-processor-id"
location: "us-central1"

# Vertex AI
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
python main.py <pdf_path> [--out-dir <dir>] [--clear-cache]
```

**처리 흐름**:
1. config.yaml 로드
2. `--out-dir` 적용, `--clear-cache` 시 캐시 삭제
3. `extract(pdf_path, config)` → paper.json 저장
4. `translate(paper, config)` → translated.json 저장
5. `compose(translated, config)` → PDF 생성
6. 원본 PDF를 output 폴더에 복사 (viewer.py 연동용)

---

## 6. viewer.py

**역할**: 원본/번역본 PDF 나란히 비교

```
python viewer.py
→ http://localhost:8765 자동 오픈
```

- `output/` 하위 폴더 탐색 → `*_번역.pdf` 파일과 원본 PDF 쌍 자동 인식
- 원본이 output 폴더에 없으면 `test_paper/`에서 탐색
- 브라우저 iframe으로 두 PDF 나란히 표시

---

## 7. 알려진 한계 및 미해결 과제

| ID | 문제 | 우선순위 | 상태 |
|----|------|----------|------|
| A | 그림 내부 래스터 OCR 텍스트 — PyMuPDF 좌표 기반 필터 불가 | 중 | 동사 필터로 부분 대응 |
| B | 컬럼 경계 단편 병합 — 소문자 시작 단편만 처리 | 중 | 부분 해결 |
| C | DocAI 참고문헌 파싱 오류 — PyMuPDF fallback | 중 | 해결 |
| D | LaTeX figure [H] 배치가 텍스트를 밀어내는 현상 | 중 | 미해결 |
| E | 표 두 열 분리 문제 | 중 | 미해결 |
| F | 전면 배치 그림 (single-column spanning figure) 처리 | 중 | 미해결 |
| G | `_fix_orphan_radicands()` 블록 내부 인라인 √ 미처리 | 하 | 이월 |
