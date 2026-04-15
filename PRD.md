# PRD — Physics-Trans v2.0
## 물리 논문 영→한 자동 번역 시스템

**버전**: 2.1
**작성일**: 2026-04-10 (최종 수정: 2026-04-15)
**작성자**: Claude (Anthropic)
**대상**: 로컬 CLI 도구 (추후 SaaS 확장 가능 구조)

---

## 1. 개요

영어로 작성된 물리학 논문 PDF를 입력받아, 수식·그림·표를 원형 그대로 보존하면서 본문을 한국어로 번역하고, XeLaTeX으로 컴파일 가능한 PDF를 출력하는 자동화 파이프라인.

---

## 2. 목표

| 구분 | 내용 |
|------|------|
| 핵심 목표 | PDF 입력 → 한국어 PDF 출력 (원클릭) |
| 품질 기준 | Adams & Riis (1997) 번역 완성본 수준 |
| 번역 스타일 | 합니다체, 학술 문어체 |
| 레이아웃 | 원본 논문 구조 유지 (1단/2단 자동 감지) |
| 수식 보존 | 인라인·디스플레이·번호부 수식 100% 원형 유지 |
| 그림 처리 | PDF에서 직접 추출한 PNG를 원본 번호 순서에 맞게 삽입 |
| 참고문헌 | 원문 그대로 유지, 번호 순 정렬 보장 |

---

## 3. 사용자 시나리오

```
$ python main.py paper.pdf --out-dir output/my_paper

[1/3] 추출 중... (extractor.py)
      ✓ 2페이지, 42블록, 8개 그림 감지
      → output/my_paper/paper.json

[2/3] 번역 중... (translator.py)
      ✓ 36블록 번역 완료
      → output/my_paper/translated.json

[3/3] 조립 중... (composer.py)
      ✓ paper_번역.tex 생성
      ✓ XeLaTeX 컴파일 완료

→ output/my_paper/paper_번역.pdf
```

---

## 4. 기능 요구사항

### 4.1 필수 기능 (MVP) ✅ 구현 완료

- [x] PDF 텍스트 블록 추출 및 구조 분류 (Google Cloud Document AI Layout Parser)
- [x] 수식 보호 후 번역, 복원 (`protect_equations` / `restore_equations`)
- [x] PDF에서 그림 PNG 추출 (DocLayout-YOLO + PyMuPDF crop)
- [x] 번역 결과 캐싱 (재실행 시 API 호출 절감)
- [x] revtex4-2 기반 한국어 LaTeX 생성
- [x] XeLaTeX 자동 컴파일 (2회, cross-reference 해소)
- [x] 1단/2단 레이아웃 자동 감지

### 4.2 품질 기능 ✅ 구현 완료

- [x] 환각 감지 (번역 결과 길이 비율 3배 초과 → 재시도)
- [x] LaTeX 유효성 검증 (`$` 짝, `{}` 깊이, `\begin/\end` 짝)
- [x] Gemini 출력 후처리 (`fix_gemini_latex()`)
- [x] 지수 백오프 재시도 (API rate limit 대응)
- [x] 그림 번호-캡션 y좌표 기반 정렬 매핑 (번호 꼬임 방지)
- [x] 그림 내부 텍스트 필터링 (동사 없는 기술 명사구 → 본문 제외)
- [x] 참고문헌 PyMuPDF fallback (DocAI 파싱 누락 시 직접 재파싱)
- [x] 컬럼 경계 문장 단편 병합 (소문자 시작 단편 → 직전 단락에 병합)

### 4.3 확장 기능 (추후)

- [ ] Railway + Cloud Run 마이크로서비스 배포
- [ ] 사용자별 토큰 잔액 관리 (PostgreSQL)
- [ ] 프론트엔드 폴링 기반 비동기 처리
- [ ] 웹 업로드 인터페이스

---

## 5. 비기능 요구사항

| 항목 | 요구사항 |
|------|----------|
| 인증 | API 키 하드코딩 금지, gcloud ADC 전용 |
| 보안 | .env, credentials 파일 .gitignore 필수 |
| 컴파일러 | XeLaTeX (한국어 폰트 필수) |
| 한국어 폰트 | NanumMyeongjo (기본) / config.yaml 변경 가능 |
| 병렬 처리 | ThreadPoolExecutor, max_workers=5 (rate limit 대응) |
| 캐시 | translated_blocks.json (블록 ID 기반) |
| 로그 | 각 단계별 진행률 출력 |
| 비교 뷰어 | viewer.py — 브라우저 기반 원본/번역본 나란히 비교 (localhost:8765) |

---

## 6. 제약사항

- Gemini 모델: `gemini-3.0-flash` (Vertex AI)
- 텍스트 파싱: Google Cloud Document AI Layout Parser (pymupdf4llm 미사용)
- 그림 탐지: DocLayout-YOLO (DocStructBench 모델)
- 수식은 번역하지 않음 (LaTeX 원형 유지)
- 참고문헌은 원문 유지
- 저자명·기관명·고유명사 번역 안 함
- 그림 캡션은 번역

---

## 7. 성공 지표

| 지표 | 목표 | 현재 상태 |
|------|------|-----------|
| 컴파일 성공률 | 테스트 논문 5편 중 5편 | 1/1 확인 |
| 수식 보존율 | 100% (플레이스홀더 복원 검증) | ✅ |
| 그림 삽입 성공률 | 캡션 번호 기준 90% 이상 | y좌표 기반 개선 완료 |
| 참고문헌 완전성 | 원본 항목 수 100% | fallback 적용 |
| 번역 환각 발생률 | 블록 기준 5% 미만 | 모니터링 중 |
