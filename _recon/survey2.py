# -*- coding: utf-8 -*-
import os, io, re, sys
from collections import defaultdict
root = r'E:\ENGINEERING_DATA'
out = io.StringIO()
def w(s=""): out.write(str(s)+"\n")
OFF = {'.doc','.docx','.dot','.dotx','.xls','.xlsx','.xlsm','.xlt','.xltx','.ppt','.pptx','.pdf','.csv','.rtf','.odt','.ods'}
bytop = defaultdict(int)
d = defaultdict(list)
for dp, dns, fns in os.walk(root):
    rel = os.path.relpath(dp, root)
    top = rel.split(os.sep)[0]
    for f in fns:
        ext = os.path.splitext(f)[1].lower()
        if ext not in OFF: continue
        bytop[top]+=1
        low = f.lower()
        if re.search(r'template|prxxxx|pdec|ka-hbrp|\btq\b|mom|sow|\bboq\b|\bmto\b|project summary|lesson learn|punch list|wcc_new|transmittal|appendix-x|payment terms|technical evaluation|weekly progress|initial assessment|rams|\bmri\b|\brfi\b', low):
            d[f].append(os.path.join(rel,f))
w("BY TOP-LEVEL FOLDER (office files):")
for k,v in sorted(bytop.items(), key=lambda x:-x[1]): w(f"  {k}: {v}")
w("\nDISTINCT TEMPLATE-LIKE BASENAMES (count, first path):")
# exclude heavy project instances: show only basenames that look like a blank template (PRXXXX / Template / no PR number)
for f in sorted(d, key=lambda x: (-len(d[x]), x)):
    w(f"  [{len(d[f]):4d}] {f}")
    w("         e.g. " + d[f][0])
sys.stdout.buffer.write(out.getvalue().encode('utf-8','replace'))
