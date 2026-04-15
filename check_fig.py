import fitz, re
doc = fitz.open('test_paper/극복 2 real.pdf')
for i, page in enumerate(doc):
    blocks = page.get_text('dict')['blocks']
    for b in blocks:
        if b['type'] == 0:
            text = ''.join(s['text'] for l in b['lines'] for s in l['spans'])
            if re.search(r'(?i)fig', text):
                print('p%d: %r' % (i+1, text[:120]))
