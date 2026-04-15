import fitz, re, sys

def _join_hyphenated_lines(lines):
    """이전 extractor 로직과 동일하게 줄 합치기"""
    if not lines:
        return ""
    result = lines[0]
    for line in lines[1:]:
        if result.endswith("-"):
            result = result[:-1] + line
        else:
            result = result + " " + line
    return result

pdf_path = "test_paper/극복 2 real.pdf"

with fitz.open(pdf_path) as doc:
    for page_num, page in enumerate(doc):
        text_dict = page.get_text("dict")
        prev_text = None
        for raw_block in text_dict.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            line_texts = []
            for line in raw_block.get("lines", []):
                span_texts = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    span_text = "".join(c for c in span_text if ord(c) >= 32 or c in "\t\n")
                    if span_text:
                        span_texts.append(span_text)
                if span_texts:
                    line_texts.append(" ".join(span_texts))
            text = _join_hyphenated_lines(line_texts)
            if not text:
                continue
            # 컬럼 경계 하이픈 단어 복원 확인
            if prev_text and prev_text.endswith("-") and re.match(r"^[a-z][a-z]{2,}[.,]?\s*$", text):
                print(f"p{page_num+1} MERGE: prev='{prev_text[-30:]}' + cur='{text[:50]}'")
            if re.match(r"^FIG\.", text, re.IGNORECASE):
                print(f"p{page_num+1} FIG block: '{text[:100]}'")
                print(f"  prev block ended: '{prev_text[-40:] if prev_text else None}'")
                print(f"  merge check: prev ends '-': {prev_text.endswith('-') if prev_text else False}")
            prev_text = text
