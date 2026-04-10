import vertexai
from vertexai.generative_models import GenerativeModel

# 1. 프로젝트 초기화
vertexai.init(project="paper-translator-potion", location="us-central1")

# 2. 모델 설정 (가장 가성비 좋은 최신 Flash 모델)
model = GenerativeModel("gemini-2.5-flash")

# 3. 테스트 질문 전송
response = model.generate_content(
    "물리학 전공자에게 멋진 인사 한마디 해줘. 그리고 현재 준비가 끝났다고 알려줘."
)

print("-" * 30)
print(f"제미나이의 답변:\n{response.text}")
print("-" * 30)