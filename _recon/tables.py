# -*- coding: utf-8 -*-
import sys, docx
for path in sys.argv[1:]:
    print("FILE:", path)
    d = docx.Document(path)
    for ti,t in enumerate(d.tables):
        print(f"  TABLE {ti}: {len(t.rows)}x{len(t.columns)}")
        for r in t.rows:
            print("    " + " || ".join(c.text.replace("\n"," / ").strip() for c in r.cells))
