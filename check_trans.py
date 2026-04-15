import json
data = json.load(open('output/translated.json', encoding='utf-8'))
blocks = data['blocks']

print("=== 전체 블록 목록 ===")
for b in blocks:
    btype = b['type']
    orig = b.get('text','')
    trans = b.get('translated_text', '')
    flag = ''
    if not any('\uac00' <= c <= '\ud7a3' for c in trans) and btype not in ('equation','reference','figure_caption'):
        flag = ' ⚠️ 미번역'
    if len(orig) > 5 and len(trans) > len(orig) * 3:
        flag += ' ⚠️ 환각'
    print(f"[{btype}]{flag}")
    print(f"  원: {orig[:70]}")
    print(f"  역: {trans[:70]}")
    print()
