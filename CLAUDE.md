# CLAUDE.md — Physics-Trans v2.0

## 프로젝트 목적
영어 물리 논문 PDF → 한국어 PDF 자동 번역 파이프라인.

## 모듈 구조
- `extractor.py` : PDF → paper.json (pymupdf4llm)
- `translator.py` : paper.json → translated.json (Vertex AI Gemini)
- `composer.py`  : translated.json → .tex → .pdf (Jinja2 + XeLaTeX)
- `utils.py`     : 수식 보호/복원, fix_gemini_latex, escape_latex, 용어사전
- `main.py`      : CLI 진입점
- `config.yaml`  : 모든 설정값 (API 키 절대 하드코딩 금지)

## 레거시 코드
- `legacy/` 폴더에 있는 파일은 로직 참고용 전용
- 수정하거나 import하지 말 것
- 새 코드는 반드시 루트에 새로 생성

## 번역 규칙
- 합니다체 사용
- 수식은 절대 번역하지 않음 (__EQ0__ 플레이스홀더 방식)
- 물리학 용어는 utils.TERM_DICT 참조
- 저자명·기관명·고유명사 번역 안 함
- 그림 캡션은 번역, Figure → 그림
- 참고문헌은 원문 유지

## 수식 보호 규칙
- utils.protect_equations() 단일 함수만 사용
- 치환 순서: $$ 먼저 → \begin{equation} → $
- 절대 extractor나 translator에 별도 구현하지 말 것

## Vertex AI 설정
- 인증: gcloud ADC (GOOGLE_APPLICATION_CREDENTIALS)
- 모델: gemini-3.0-flash
- max_workers: 5 (rate limit 대응)
- 하드코딩된 API 키 절대 금지

## LaTeX/컴파일 설정
- 컴파일러: XeLaTeX
- 명령어: xelatex -interaction=nonstopmode {tex_file}
- 2회 반복 컴파일 (cross-reference)
- 한국어 폰트: NanumMyeongjo (config.yaml에서 변경 가능)
- 문서 클래스: revtex4-2

## 품질 기준
- 참고 완성본: Adams & Riis (1997) 번역본
- 레이아웃: 1단(single-column)
- 환각 감지: 길이 3배 초과 OR 수식 플레이스홀더 소실

## 구현 순서
1. utils.py (수식 보호/복원 단일 정의)
2. extractor.py (PDF → JSON, 그림 추출 포함)
3. translator.py (Vertex AI 연동, 캐시, 병렬)
4. composer.py (Jinja2 템플릿 + XeLaTeX)
5. main.py (통합)
6. 통합 테스트 (Adams & Riis 전체 실행)

## 각 단계 완료 조건
- extractor: 테스트 PDF → paper.json 출력, 그림 PNG 파일 생성 확인
- translator: 단일 블록 번역 성공, 캐시 저장 확인
- composer: .tex 생성 + XeLaTeX 컴파일 성공, PDF 출력 확인

