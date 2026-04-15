import fitz

pdf_path = "test_paper/극복 2 real.pdf"

with fitz.open(pdf_path) as doc:
    page = doc[1]  # p2
    text_dict = page.get_text("dict")
    raw_block = text_dict["blocks"][6]  # FIG. 1 block
    print("block type:", raw_block.get("type"))
    print("bbox:", raw_block.get("bbox"))
    for li, line in enumerate(raw_block.get("lines", [])):
        print(f"  line {li}:")
        for si, span in enumerate(line.get("spans", [])):
            print(f"    span {si}: text={repr(span.get('text',''))[:60]}, size={span.get('size')}, flags={span.get('flags')}")
