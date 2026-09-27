import zipfile, re
from pathlib import Path
p = Path('backend/templates/mom_template.docx')
with zipfile.ZipFile(p) as z:
    xml = z.read('word/document.xml').decode('utf-8', 'replace')

# paragraph and table markers in document order
body = xml.split('<w:body>', 1)[1]
tokens = re.findall(r'<w:p[ >]|<w:tbl>|<w:tbl>|</w:tbl>', body)
# print an outline: each paragraph's plain text (truncated) and table boundaries
parts = re.split(r'(<w:tbl>.*?</w:tbl>)', body, flags=re.S)
idx = 0
for part in parts[:14]:
    if part.startswith('<w:tbl>'):
        rows = part.count('<w:tr')
        text = re.sub(r'<[^>]+>', ' ', part)
        text = ' '.join(text.split())[:110]
        print(f'[TABLE rows={rows}] {text}')
    else:
        for para in re.findall(r'<w:p[ >].*?</w:p>', part, flags=re.S):
            text = re.sub(r'<[^>]+>', '', para)
            text = ' '.join(text.split())
            print(f'  p: {text[:110]}')
