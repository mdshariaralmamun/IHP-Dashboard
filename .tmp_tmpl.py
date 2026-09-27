import re, zipfile
from pathlib import Path
p = Path('backend/templates/mom_template.docx')
with zipfile.ZipFile(p) as z:
    names = z.namelist()
    xml = z.read('word/document.xml').decode('utf-8', 'replace')
# Jinja tags can be split across runs; normalise by stripping tags between {{ }} parts
plain = re.sub(r'<[^>]+>', '', xml)
tags = re.findall(r'\{\{[^}]*\}\}|\{%[^%]*%\}', plain)
print('file size:', p.stat().st_size, '| parts:', len(names))
print('tags found:', len(tags))
for t in dict.fromkeys(tags):
    print('  ', t)
print()
print('has agenda loop:', '{%tr' in plain or '{% for' in plain)
