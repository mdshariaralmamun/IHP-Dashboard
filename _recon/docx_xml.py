# -*- coding: utf-8 -*-
import sys, zipfile, re, io
path = sys.argv[1]
out = io.StringIO()
def w(s=""):
    out.write(str(s)+"\n")
w("FILE: "+path)
w("="*100)

z = zipfile.ZipFile(path)
names = z.namelist()
w("\n### ZIP PARTS ###")
for n in names:
    try:
        sz = z.getinfo(n).file_size
    except Exception:
        sz = -1
    w(f"  {n}  ({sz} bytes)")

docxml = z.read("word/document.xml").decode("utf-8", "replace")

w("\n### FIELD / MERGE MARKERS in document.xml ###")
for marker in ["MERGEFIELD","fldSimple","w:sdt","w:sdtPr","w:instrText","fldChar","w:dataBinding","SHAPE","w:fldChar"]:
    w(f"  {marker}: {docxml.count(marker)} occurrence(s)")

# All instrText contents
w("\n### instrText CONTENTS (document.xml) ###")
instrs = re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>", docxml, re.S)
for i,s in enumerate(instrs):
    w(f"  [{i}] {s}")

w("\n### MERGEFIELD names in document order ###")
# find MERGEFIELD occurrences with surrounding text
for m in re.finditer(r"MERGEFIELD", docxml):
    seg = docxml[m.start():m.start()+200]
    nm = re.search(r'MERGEFIELD\s+("([^"]+)"|([^\\<>&]+))', seg)
    w("  " + (nm.group(0) if nm else seg[:120]))

w("\n### sdt blocks (content controls) ###")
for m in re.finditer(r"<w:sdt>", docxml):
    seg = docxml[m.start():m.start()+600]
    w("  ---- sdt at %d ----" % m.start())
    for tag in re.findall(r"<w:(alias|tag|docPartObj)[^>]*w:val=\"([^\"]*)\"", seg):
        w("     " + str(tag))
    txts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", seg, re.S)
    w("     text: " + " | ".join(txts[:8]))

# headers/footers
w("\n### HEADERS / FOOTERS ###")
for n in names:
    if re.match(r"word/(header|footer)\d*\.xml$", n):
        x = z.read(n).decode("utf-8","replace")
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", x, re.S)
        w(f"  -- {n} --")
        w("     text: " + " | ".join(texts))
        fi = re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>", x, re.S)
        if fi:
            w("     fields: " + " | ".join(fi))
        w("     PAGE field: %s, NUMPAGES: %s, MERGEFIELD: %s" % ("PAGE" in x, "NUMPAGES" in x, "MERGEFIELD" in x))

sys.stdout.buffer.write(out.getvalue().encode("utf-8"))
