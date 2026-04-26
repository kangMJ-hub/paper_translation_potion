from google import genai

# 1. Vertex AI + global endpoint 초기화
client = genai.Client(
    vertexai=True,
    project="paper-translator-potion",
    location="global"
)

# 2. 모델 설정
MODEL = "gemini-3-flash-preview"

# 3. 테스트 질문 전송
response = client.models.generate_content(
    model=MODEL,
    contents="물리학 전공자에게 멋진 인사 한마디 해줘. 그리고 현재 준비가 끝났다고 알려줘."
)

print("-" * 30)
print(f"제미나이의 답변:\n{response.text}")
print("-" * 30)
