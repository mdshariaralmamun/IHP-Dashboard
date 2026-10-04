# -*- coding: utf-8 -*-
import os, io, re, sys
root = r'E:\ENGINEERING_DATA'
out = io.StringIO()
def w(s=""): out.write(str(s)+"\n")
OFF = {'.doc','.docx','.dot','.dotx','.xls','.xlsx','.xlsm','.xlt','.xltx','.ppt','.pptx','.pdf','.csv','.rtf','.odt','.ods','.txt','.md'}
bytop = {}
templike = []
alloffice = 0
for dp, dns, fns in os.walk(root):
    rel = os.path.relpath(dp, root)
    top = rel.split(os.sep)[0]
    for f in fns:
        ext = os.path.splitext(f)[1].lower()
        if ext not in OFF: continue
        alloffice += 1
        bytop[top] = bytop.get(top,0)+1
        low = f.lower()
        if re.search(r'template|prxxxx|pdec|ka-hbrp|\btq\b|mom|sow|\bboq\b|\bmto\b|project summary|cost est|lesson learn|punch list|wcc_new|transmittal|appendix-x|payment terms|technical evaluation|weekly progress meeting', low):
            templike.append((top, rel, f))
w("TOTAL office files: %d" % alloffice)
w("\nBY TOP-LEVEL FOLDER:")
for k,v in sorted(bytop.items(), key=lambda x:-x[1]):
    w(f"  {k}: {v}")
w("\nTEMPLATE-LIKE FILES (grouped, unique basenames):")
from collections import defaultdict
d = defaultdict(list)
for top, rel, f in templike:
    d[f].append(os.path.join(rel))
# print unique basename counts and up to 3 example paths
for f in sorted(d, key=lambda x: -len(d[x])):
    w(f"  [{len(d[f])}] {f}")
    for p in d[f][:3]:
        w("        "+p)
sys.stdout.buffer.write(out.getvalue().encode('utf-8','replace'))
