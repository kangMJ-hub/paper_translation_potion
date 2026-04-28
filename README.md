# Physics-Trans

영어 물리학 논문 PDF를 한국어 PDF로 자동 번역하는 프로그램입니다.

Google Cloud Document AI로 논문 구조를 분석하고, Vertex AI Gemini로 번역한 뒤, XeLaTeX으로 한국어 PDF를 생성합니다.

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [Python 패키지 설치](#2-python-패키지-설치)
3. [외부 프로그램 설치](#3-외부-프로그램-설치)
4. [Google Cloud 설정](#4-google-cloud-설정)
5. [실행 방법](#5-실행-방법)

---

## 1. 사전 요구사항

- Python 3.10 이상
- 인터넷 연결 (Google Cloud 서비스 사용)
- Google 계정 및 GCP(Google Cloud Platform) 프로젝트

---

## 2. Python 패키지 설치

```bash
pip install pymupdf pymupdf4llm
pip install google-cloud-aiplatform vertexai google-cloud-documentai
pip install jinja2 pyyaml
pip install doclayout-yolo huggingface_hub ultralytics
```

> 첫 실행 시 DocLayout-YOLO 모델 가중치가 Hugging Face에서 자동으로 다운로드됩니다 (약 500MB). 이후 실행부터는 로컬 캐시를 사용합니다.

---

## 3. 외부 프로그램 설치

### XeLaTeX

한국어 PDF 생성에 필요합니다.

- **Windows**: [MiKTeX](https://miktex.org/download) 설치 권장
- **macOS**: `brew install --cask mactex`
- **Linux**: `sudo apt install texlive-xetex`

설치 후 터미널에서 확인:
```bash
xelatex --version
```

### 한국어 폰트

기본 설정은 **UnBatang / UnDotum** 폰트를 사용합니다.

- **Windows**: [은글꼴(Un fonts)](https://kldp.net/unfonts/) 다운로드 후 설치
- 또는 `config.yaml`에서 시스템에 설치된 다른 한국어 폰트로 변경 가능

### Google Cloud SDK

Google Cloud 인증에 필요합니다.

1. [Google Cloud SDK 다운로드](https://cloud.google.com/sdk/docs/install) 후 설치
2. 설치 완료 후 터미널(또는 Google Cloud SDK Shell)에서 실행:

```bash
gcloud auth application-default login
```

브라우저가 열리면 Google 계정으로 로그인합니다. 이후 프로그램이 자동으로 인증 정보를 사용합니다.

---

## 4. Google Cloud 설정

### 4-1. GCP 프로젝트 생성

1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. 상단 프로젝트 선택 → **새 프로젝트** 생성
3. 프로젝트 ID를 메모해둡니다 (예: `my-paper-translator`)

### 4-2. API 활성화

생성한 프로젝트에서 아래 두 API를 활성화합니다.

- [Document AI API 활성화](https://console.cloud.google.com/apis/library/documentai.googleapis.com)
- [Vertex AI API 활성화](https://console.cloud.google.com/apis/library/aiplatform.googleapis.com)

각 링크 접속 후 **사용 설정** 버튼을 클릭합니다.

### 4-3. Document AI 프로세서 생성

1. [Document AI 콘솔](https://console.cloud.google.com/ai/document-ai) 접속
2. **프로세서 만들기** 클릭
3. **Layout Parser** 선택
4. 리전: `us` 선택, 이름 입력 후 생성
5. 생성된 프로세서의 **프로세서 ID**를 메모합니다 (예: `abc123def456`)

### 4-4. config.yaml 설정

프로젝트 루트의 `config.yaml`을 열어 아래 항목을 본인 정보로 수정합니다:

```yaml
project_id: "여기에-GCP-프로젝트-ID"
docai_processor_id: "여기에-프로세서-ID"
```

폰트를 변경하고 싶은 경우:
```yaml
main_font: "NanumMyeongjo"   # 시스템에 설치된 폰트명으로 변경
sans_font: "NanumGothic"
```

---

## 5. 실행 방법

### GUI 실행 (권장)

```bash
python gui.py
```

또는 `gui_runner.pyw`를 더블클릭하면 터미널 창 없이 실행됩니다.

1. **PDF 선택** 버튼으로 번역할 논문 PDF를 선택
2. **번역 시작** 버튼 클릭
3. 완료되면 `output/` 폴더에 번역된 PDF가 생성됩니다

### CLI 실행

```bash
python main.py "논문.pdf"
```

특정 config 파일을 지정하려면:
```bash
python main.py "논문.pdf" --config config.yaml
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/논문명_번역.pdf` | 최종 번역 PDF |
| `output/paper.json` | 추출된 논문 구조 |
| `output/translated.json` | 번역 결과 |
| `output/figures/` | 추출된 그림/수식 이미지 |
