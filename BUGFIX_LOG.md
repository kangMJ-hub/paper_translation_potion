# Physics-Trans v2.0 — 버그 수정 목록

---

## [2026-04-13] 번역 품질 이슈 수정

### BUG-01: LaTeX 이스케이프 오류 (단락 내 bare LaTeX 명령어)
**증상**: 번역기(Gemini)가 본문 단락에 `\rightarrow`, `Cl_{2}^{+}` 같은 LaTeX를 `$...$` 없이 날것으로 출력 → `escape_latex`가 `\` → `\textbackslash{}`, `_` → `\_` 등으로 이중 이스케이프
**예시**: `Cl_{2}^{+}` → `\{Cl\_\{2\}\}\^{}\{+\}` (렌더링 불가)
**수정 파일**: `utils.py`, `composer.py`
**수정 내용**:
- `utils.py`에 `wrap_bare_latex_in_text()` 함수 추가: `$...$` 밖의 subscript/superscript 패턴(`word_{...}`, `word^{...}`)과 수학 명령어(`\rightarrow`, `\pm` 등)를 `$...$`로 자동 감싸기
- `composer.py` `_escape_latex_text()`에서 `escape_latex` 적용 전에 `wrap_bare_latex_in_text()` 호출

---

### BUG-02: 수식 블록 내 `$...$` 이중 감싸기로 컴파일 실패
**증상**: 번역기가 수식 텍스트에 `$...$`를 남긴 채 반환 → `\begin{equation}` 안에 `$...$`가 들어가 LaTeX 컴파일 오류 (`Display math should end with $$`, `Missing $ inserted`)
**수정 파일**: `composer.py`
**수정 내용**: `_filter_format_equation()`에서 `eq_text` 생성 후 `^\$...\$$` 패턴을 정규식으로 제거

---

### BUG-03: 측정값이 `\begin{equation}`으로 잘못 분류
**증상**: 그림 캡션 데이터 `87 nm ± 1.4 nm 3σ` 같은 측정값이 DocAI에 의해 equation 블록으로 분류되어 numbered equation으로 출력
**수정 파일**: `composer.py`
**수정 내용**: `_filter_format_equation()`에서 등호(`=`, `≡`, `≈` 등) 없이 숫자로 시작하는 단일 줄 수식 → `_escape_latex_text()`로 인라인 텍스트 처리

---

### BUG-04: 그림 내부 축 레이블이 본문에 누출
**증상**: DocAI가 그림 내 축 레이블(`0 -150-100-50 0 50 100 150 웨이퍼 단면 (mm)`)을 별도 paragraph 블록으로 추출
**수정 파일**: `extractor.py`
**수정 내용**: `_classify_paragraph()`에 패턴 추가 — 숫자 수열로 시작하고 한국어 단위가 뒤따르는 100자 미만 텍스트 → `skip`

---

### BUG-05: 서브그림 레이블이 본문에 누출
**증상**: DocAI가 그림 내 서브그림 레이블(`(d)........`)을 본문 paragraph로 추출
**수정 파일**: `extractor.py`
**수정 내용**: `_classify_paragraph()`에 패턴 추가 — `(a)`, `(b)` 등 괄호 영문자 뒤 점/공백만 있는 텍스트 → `skip`

---

### BUG-06: `wrap_bare_latex_in_text` 이중 감싸기 버그 (`$15^{$\circ$}$`)
**증상**: `15^{\circ}C` 처리 시 `_BARE_SUBSUP`이 `$15^{\circ}$`로 감싼 뒤, `_BARE_LATEX_CMDS`가 이미 `$...$` 안의 `\circ`를 또 `$\circ$`로 감싸서 `$15^{$\circ$}$` 생성 → LaTeX 컴파일 오류
**수정 파일**: `utils.py`
**수정 내용**: `wrap_bare_latex_in_text()`에서 `_BARE_SUBSUP` 적용 후 새로 생긴 `$...$`를 재분리하여 보호한 뒤 `_BARE_LATEX_CMDS` 적용 (이중 감싸기 방지)

---

## [2026-04-14] 버그 수정

### BUG-07: 번역 실패 결과가 캐시에 저장되어 영어 단락 누출
**증상**: 번역에 실패한 영어 단락이 원문 그대로 캐시에 저장되어, 이후 실행에서 재번역 없이 영어 그대로 출력
**수정 파일**: `translator.py`
**수정 내용**: `translate_one()`에서 번역 결과가 원문과 동일하고 한국어가 없는 경우(`is_failed`) 캐시에 저장하지 않아 다음 실행 시 자동 재시도

---

### BUG-08: SEM/TEM 장비 메타데이터 본문 누출
**증상**: `S4700 20.0kV 12.0mm x450 SE(M)` 같은 전자현미경 이미지 메타데이터가 본문 단락으로 출력
**수정 파일**: `extractor.py`
**수정 내용**: `_classify_paragraph()`에 패턴 추가 — `kV`, `x\d{2,5}`, `SE(X)`, `BSE`, `ETD` 패턴 + 80자 미만 + 한국어 없음 → `skip`

---

### BUG-09: 번호 없는 참고문헌 bibitem 키 전부 `refh1` 중복
**증상**: 번호 없는 참고문헌 항목이 모두 `\bibitem{refh1}`로 동일한 키 생성 → LaTeX 중복 키 경고, 상호 인용 불가
**수정 파일**: `template.tex.j2`
**수정 내용**: 중첩 루프 내 `loop.index`는 외부 루프마다 1로 리셋되는 문제 → Jinja2 `namespace(ref_counter=0)` 전역 카운터로 교체하여 고유 키(`refh1`, `refh2`, ...) 보장

---

### BUG-10: "References" 헤딩이 paragraph로 분류될 때 참고문헌 섹션 미인식
**증상**: DocAI가 "References" 헤딩을 `section`이 아닌 `paragraph`로 분류하면 `in_ref_section`이 활성화되지 않아 이후 참고문헌 블록이 일반 단락으로 처리됨
**수정 파일**: `extractor.py`, `composer.py`
**수정 내용**: `_reclassify_ref_section()` 및 composer 재분류 로직에서 `paragraph` 타입도 References 헤딩 감지 대상에 포함

---

## [2026-04-14] 한계 5_번역.pdf 검수 결과 — 수정 완료

### ISSUE-A: 번역 누락 — 영어 단락이 그대로 출력 ✅ 수정
**증상**: 영어 단락이 번역되지 않고 그대로 출력됨
**근본 원인**: `translator.py`의 `translate_one()`에서 번역 실패(원문 반환) 값이 캐시에 저장됨 → 이후 실행 시 영어 원문이 cache hit되어 재번역 없이 그대로 사용
**수정**: `translator.py` — 번역 결과가 원문과 동일하고 한국어가 없는 경우(`is_failed`) 캐시에 저장하지 않아 다음 실행 시 재시도

### ISSUE-B: SEM 장비 메타데이터 본문 누출 ✅ 수정
**증상**: `S4700 20.0kV 12.0mm x450 SE(M)` 같은 전자현미경 메타데이터가 본문에 출력됨
**근본 원인**: `_classify_paragraph()`에 SEM/TEM 파라미터 패턴 필터 없음
**수정**: `extractor.py` — `kV`, `x\d{2,5}`, `SE(M)`, `BSE`, `ETD` 패턴 + 80자 미만 + 한국어 없음 → `skip`

### ISSUE-C: 참고문헌 bibitem 키 중복 (`refh1` 반복) ✅ 수정
**증상**: 모든 번호 없는 참고문헌이 `\bibitem{refh1}`로 동일한 키 → 인용 불가
**근본 원인**: `template.tex.j2` 중첩 루프에서 내부 `loop.index`가 외부 루프 반복마다 1로 리셋
**수정**: `template.tex.j2` — Jinja2 `namespace(ref_counter=0)` 전역 카운터로 교체

### ISSUE-D: 참고문헌 번호 대거 누락 — 부분 수정 ⚠️
**증상**: 일부 참고문헌이 섹션에 미출력
**원인 1 (수정)**: "References" 헤딩이 `paragraph` 타입으로 분류될 때 `in_ref_section` 미활성화
  → `extractor.py`·`composer.py` 모두에서 `paragraph` 타입도 헤딩 감지 대상에 추가
**원인 2 (미수정)**: DocAI 자체가 해당 텍스트 블록을 미추출 — 코드로 복원 불가

### ISSUE-E: 참고문헌 항목 불완전 (텍스트 중간 잘림) — 미수정
**원인**: DocAI 추출 한계 — 긴 텍스트 블록 잘림 현상, 코드 수정으로 해결 불가

---

## [2026-04-14] 스모크 테스트 발견 — 미수정 버그

### BUG-11: Vertex AI 응답 utf-8 디코딩 오류 ✅ 수정
**증상**: `'utf-8' codec can't decode byte 0xb3 in position 23: invalid start byte` — 추출 단계에서 반복 발생 → 4×30s 재시도 딜레이
**근본 원인**: `_init_vertex()`의 CP949 패치가 `finally` 블록으로 원복되어, 이후 `generate_content()` 첫 호출 시 lazy credential 로딩 시 CP949 오류 재발
**수정**: `translator.py` — `finally` 블록 제거, `_cs._cp949_patched` 플래그로 중복 패치 방지하며 세션 전체에 패치 유지

---

### BUG-12: LaTeX 컴파일 실패 — `{` 미닫힘 및 `\textbackslash{}` 수식 누출
**증상**: `여는 { 가 닫히지 않았습니다 (미닫힌 깊이: 3)`, `! Missing } inserted.`, `! Missing $ inserted.`
**발견**: hep-ph `2604.05612v2.pdf` — PDF 생성 실패
**원인 후보**:
- 단락 내 `\sigma`, `\simeq` 등 bare LaTeX가 `escape_latex`에 의해 `\textbackslash{}simeq`로 이중 이스케이프
- `$X_{K^{+}$\}` — Gemini가 subscript 내부에 `$` 삽입하여 수식 미닫힘
- `\begin{aligned}...\}\}\}` — 수식 끝 여분의 `}` 3개
**상태**: 미수정 (`.tex` 파일 분석 후 수정 예정: `output/smoke_hep-ph/2604.05612v2_번역.tex`)

---

## [이전] 주요 기능 구현 및 버그 수정

### DocLayout-YOLO 그림 감지 통합
- `_yolo_detect_bboxes()`: figure + table bbox 동시 반환
- YOLO 페이지 렌더링 크롭을 1순위 추출 방식으로 채택 (벡터 그래픽 + 합성 그림 지원)
- 래스터 직접 추출은 YOLO 미감지 시 폴백으로 유지

### 소프트 마스크(smask) 처리 — 검은 배경 버그 수정
**증상**: cs=3(RGB) 이미지에 투명도(smask)가 있을 때 흰 배경 대신 검은 배경으로 저장
**수정**: `extract_image(smask_xref)`로 마스크 추출 후 PIL로 흰 배경에 합성

### 그림 순서 오류 수정
**증상**: DocAI가 캡션을 레이아웃 순서로 반환하여 그림 번호 순서가 뒤바뀜
**수정**: `fig_captions`를 그림 번호(`re.search(r"(\d+)")`) 기준으로 정렬

### 참고문헌 이중 번호 수정 (`[1][1]` 문제)
**증상**: `\bibitem` LaTeX 자동 번호 + 텍스트 `[1]` 이 중복 출력
**수정**: `\bibitem[N]{refN}` 형식 사용 + `strip_ref_num` 필터로 텍스트에서 번호 제거

### 참고문헌 오분류 수정
**증상**: `"2. Steady-state active-glow period"` 같은 소절 제목이 reference로 분류
**수정**: `_classify_paragraph()`에서 `^\d+\.\s+[A-Z][a-z]` 패턴 제거, `[N]` 형식만 reference로 분류

### 파일 정리 확장
**증상**: 논문 전환 시 `.tex`, `.aux`, `.log`, `.out`, `.bib` 파일 미삭제
**수정**: `main.py` cleanup glob 패턴에 해당 확장자 추가

### 그림 크기 조정
**수정**: `\includegraphics[width=...]` → `\adjustbox{max totalsize={0.32\columnwidth}{0.18\textheight}}`로 변경 (비율 유지하며 최대 크기 제한)
