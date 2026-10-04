# -*- coding: utf-8 -*-
import sys, io
from pypdf import PdfReader
path = sys.argv[1]
npages = int(sys.argv[2]) if len(sys.argv)>2 and sys.argv[2] else 2
outpath = sys.argv[3] if len(sys.argv)>3 else None
out = io.StringIO()
def w(s=""): out.write(str(s)+"\n")
r = PdfReader(path)
w("FILE: "+path)
w("pages: %d" % len(r.pages))
try:
    w("metadata: "+str(dict(r.metadata)))
except Exception as e:
    w("metadata err "+str(e))
for i in range(min(npages, len(r.pages))):
    t = r.pages[i].extract_text() or ""
    w("\n"+"="*90)
    w(f"### PAGE {i+1} TEXT ###")
    w(t)
data = out.getvalue().encode("utf-8")
if outpath:
    open(outpath,"wb").write(data)
    print("wrote", outpath, len(data))
else:
    sys.stdout.buffer.write(data)
