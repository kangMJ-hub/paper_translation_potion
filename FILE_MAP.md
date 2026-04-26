# Physics-Trans v2.0 — 파일 구조 및 역할 정리

## 핵심 파이프라인 모듈

| 파일 | 역할 |
|------|------|
| `main.py` | CLI 진입점. `--out-dir`, `--skip-extract`, `--skip-translate` 등 옵션 처리 후 extractor → translator → composer 순으로 파이프라인 실행 |
| `extractor.py` | PDF → `paper.json`. pymupdf4llm으로 텍스트 추출, 블록 분류(제목/본문/수식/캡션/참고문헌 등), 레이아웃 감지(1단/2단), 그림 PNG 추출 |
| `translator.py` | `paper.json` → `translated.json`. Vertex AI Gemini 호출, 블록 단위 병렬 번역(max_workers=5), 블록 캐시(`translated_blocks.json`) 관리 |
| `composer.py` | `translated.json` → `.tex` → `.pdf`. Jinja2 템플릿 렌더링 후 XeLaTeX 2회 컴파일 |
| `utils.py` | 공통 유틸리티. 수식 보호/복원(`protect_equations`/`restore_equations`), LaTeX 이스케이프(`escape_latex`), Gemini 출력 후처리(`fix_gemini_latex`), 물리 용어사전(`TERM_DICT`) |
| `template.tex.j2` | Jinja2 LaTeX 템플릿. revtex4-2 문서클래스, NanumMyeongjo 한국어 폰트, 블록 타입별 렌더링 규칙 정의 |

---

## 설정 파일

| 파일 | 역할 |
|------|------|
| `config.yaml` | 전체 설정값. Vertex AI project_id·location·model, Document AI processor 정보, 출력 디렉토리, 폰트명 등. API 키 하드코딩 금지 |
| `requirements.txt` | Python 패키지 의존성 목록 (pymupdf, pymupdf4llm, google-cloud-aiplatform, vertexai, jinja2, pyyaml) |
| `CLAUDE.md` | Claude Code용 프로젝트 지시서. 번역 규칙, 수식 보호 규칙, Vertex AI 설정, 구현 순서, 완료 조건 등 |

---

## 문서

| 파일 | 역할 |
|------|------|
| `PRD.md` | Product Requirements Document. 시스템 목적, 기능 요구사항, 품질 기준 정의 |
| `TRD.md` | Technical Requirements Document. 기술 설계, 모듈별 인터페이스, 데이터 흐름 명세 |
| `BUGFIX_LOG.md` | 버그 수정 이력. 날짜별 원인·수정 내용·영향 범위 기록 |
| `FILE_MAP.md` | 본 파일. 프로젝트 파일 구조 및 역할 정리 |

---

## 유틸리티 / 개발 도구

| 파일 | 역할 |
|------|------|
| `viewer.py` | 원본/번역본 PDF 나란히 비교 뷰어. `python viewer.py` 실행 후 `http://localhost:8765` 접속 |
| `clean.py` | output 디렉토리 초기화 스크립트. `--all`(figures 포함), `--smoke`(smoke_* 서브디렉토리만) 옵션 지원 |
| `download_papers.py` | arXiv API로 분야별(quant-ph, cond-mat, hep-ph, nucl-th, astro-ph) 10페이지 이하 논문 PDF를 `tests/papers/`에 20편씩 다운로드 |
| `check_trans.py` | `translated.json` 블록별 번역 결과 출력. 미번역·환각 블록 자동 플래그 표시 |
| `check_fig.py` | PDF에서 "FIG" 포함 블록 탐색 — 그림 캡션 추출 확인용 |
| `debug_docai.py` | Document AI API 직접 호출 테스트 스크립트 |
| `debug_fig.py` | pymupdf 블록 단위 그림 캡션 탐지 디버그 스크립트 |
| `debug_fig2.py` | 특정 페이지·블록의 span 상세 정보 출력 디버그 스크립트 |
| `test_gemini.py` | Gemini API 단독 호출 테스트 스크립트 |

---

## 디렉토리

| 경로 | 역할 |
|------|------|
| `output/` | 파이프라인 출력 디렉토리. `paper.json`, `translated.json`, `.tex`, `.pdf`, 그림 PNG 등 저장. `smoke_*/` 서브디렉토리는 분야별 테스트 격리 출력 |
| `output/figures/` | 추출된 그림 PNG 파일 저장소 |
| `tests/papers/` | 분야별(`astro-ph`, `cond-mat`, `hep-ph`, `nucl-th`, `quant-ph`) 테스트용 논문 PDF 모음 |
| `tests/tested_papers.md` | 테스트 완료 논문 목록 기록 파일 |
| `legacy/` | 이전 버전 코드 참고용 보관 폴더. 수정·import 금지 |
|

---