import yaml
from google.api_core.client_options import ClientOptions
from google.cloud import documentai

with open("config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

project_id   = cfg["project_id"]
location     = cfg["docai_location"]
processor_id = cfg["docai_processor_id"]

opts   = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
client = documentai.DocumentProcessorServiceClient(client_options=opts)
name   = client.processor_path(project_id, location, processor_id)

with open("test_paper/극복 3 real.pdf", "rb") as f:
    pdf_bytes = f.read()

print(f"PDF size: {len(pdf_bytes):,} bytes")

result = client.process_document(request=documentai.ProcessRequest(
    name=name,
    raw_document=documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf"),
))
doc = result.document

print(f"pages: {len(doc.pages)}")
print(f"text length: {len(doc.text)}")

# document_layout 필드 확인
dl = doc.document_layout
if dl:
    print(f"document_layout blocks: {len(dl.blocks)}")
    for i, b in enumerate(dl.blocks[:5]):
        print(f"  block {i}: {b}")
else:
    print("document_layout: None")

# entities 확인
print(f"entities: {len(doc.entities)}")

# 전체 응답 타입 확인
print(f"\ndoc fields: {[f.name for f in doc.DESCRIPTOR.fields]}")
