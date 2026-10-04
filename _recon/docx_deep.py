# -*- coding: utf-8 -*-
import sys, zipfile, re, io
path = sys.argv[1]
out = io.StringIO()
def w(s=""): out.write(str(s)+"\n")
z = zipfile.ZipFile(path)
doc = z.read("word/document.xml").decode("utf-8","replace")

w("FILE: "+path)
w("\n### ALL LOCKED/SDT CONTENT CONTROLS (w:sdt elements incl. nested) ###")
# find each <w:sdt ...> ... matching; use non-greedy to </w:sdt>
cnt=0
for m in re.finditer(r"<w:sdt>(.*?)</w:sdt>", doc, re.S):
    blk = m.group(1)
    cnt+=1
    alias = re.search(r'<w:alias w:val="([^"]*)"', blk)
    tag = re.search(r'<w:tag w:val="([^"]*)"', blk)
    typ = re.search(r'<w:(text|dropDownList|comboBox|date|checkbox|richText|picture|docPartObj|buildingBlockGallery)[ />]', blk)
    texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", blk, re.S)
    # find preceding text in doc
    pre = doc[max(0,m.start()-600):m.start()]
    pretexts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", pre, re.S)
    w(f"  #{cnt} alias={alias.group(1) if alias else None!r} tag={tag.group(1) if tag else None!r} type={typ.group(1) if typ else None!r}")
    w(f"      ctrl text: {' | '.join(texts)}")
    w(f"      preceding text: {' | '.join(pretexts[-6:])}")
w("total <w:sdt> blocks: %d" % cnt)

w("\n### customXml item*.xml CONTENT ###")
for n in z.namelist():
    if re.match(r"customXml/item\d+\.xml$", n):
        c = z.read(n).decode("utf-8","replace")
        w("--- "+n+" ---")
        w(c[:2500])

w("\n### glossary (AutoText) document.xml TEXT ###")
g = z.read("word/glossary/document.xml").decode("utf-8","replace")
gtexts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", g, re.S)
w("texts: " + " | ".join(gtexts))

w("\n### HEADER/FOOTER FULL PARAGRAPH DUMPS ###")
for n in z.namelist():
    if re.match(r"word/(header|footer)\d*\.xml$", n):
        x = z.read(n).decode("utf-8","replace")
        w("--- "+n+" ---")
        for pi,pm in enumerate(re.finditer(r"<w:p[ >].*?</w:p>", x, re.S)):
            blk = pm.group(0)
            ts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", blk, re.S)
            instr = re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>", blk, re.S)
            drw = ("w:drawing" in blk) or ("v:imagedata" in blk) or ("w:pict" in blk)
            w(f"   p{pi}: text={' | '.join(ts)}  fields={instr}  image={drw}")

w("\n### STYLES: default docDefaults + Normal + heading styles ###")
st = z.read("word/styles.xml").decode("utf-8","replace")
m = re.search(r"<w:docDefaults>.*?</w:docDefaults>", st, re.S)
if m: w("docDefaults:\n"+m.group(0)[:1500])
# each style w/ name, basedOn, font, size, spacing, indent
w("\n--- style definitions (name, font ascii, sz, spacing) ---")
for sm in re.finditer(r"<w:style [^>]*w:styleId=\"([^\"]+)\".*?</w:style>", st, re.S):
    blk = sm.group(0)
    nm = re.search(r'<w:name w:val="([^"]*)"', blk)
    fonts = re.findall(r'w:ascii="([^"]*)"', blk)
    sz = re.findall(r'<w:sz w:val="([^"]*)"', blk)
    spc = re.findall(r'<w:spacing([^/]*)/>', blk)
    ind = re.findall(r'<w:ind([^/]*)/>', blk)
    if nm and (nm.group(1) in ("Normal","Heading 1","Heading 2","Heading 3","Title","Default","List Paragraph","Subtitle") or len(fonts)+len(sz)+len(spc)):
        w(f"  styleId={sm.group(1)} name={nm.group(1)!r} fonts={fonts} sz={sz} spacing={spc[:2]} ind={ind[:2]}")

w("\n### docProps/core.xml ###")
w(z.read("docProps/core.xml").decode("utf-8","replace"))
w("\n### docProps/custom.xml ###")
w(z.read("docProps/custom.xml").decode("utf-8","replace"))

sys.stdout.buffer.write(out.getvalue().encode("utf-8"))
