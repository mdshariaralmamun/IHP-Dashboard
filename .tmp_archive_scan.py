"""Bounded recon of the local engineering archive (what is worth indexing)."""
import sys, time
from collections import Counter
from pathlib import Path

ROOTS = [Path(r"E:\ENGINEERING_DATA\IHP_Projects"), Path(r"E:\ENGINEERING_DATA\archives")]
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xlsm", ".xls", ".txt", ".md", ".csv", ".msg", ".pptx"}
MAX_BYTES = 20 * 1024 * 1024
deadline = time.time() + 150

by_ext = Counter()
size_by_ext = Counter()
doc_files = []
total_files = 0
for root in ROOTS:
    if not root.is_dir():
        continue
    for path in root.rglob("*"):
        if time.time() > deadline:
            print("!! scan deadline hit, partial results")
            break
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        total_files += 1
        ext = path.suffix.lower()
        by_ext[ext] += 1
        try:
            size = path.stat().st_size
        except OSError:
            continue
        size_by_ext[ext] += size
        if ext in DOC_EXT and size <= MAX_BYTES:
            doc_files.append((ext, size))

print("total files walked:", total_files)
print("top extensions by count:")
for ext, n in by_ext.most_common(18):
    print(f"   {ext or '(none)':8} {n:7}  {size_by_ext[ext]/1e6:10.1f} MB")
print()
print("indexable docs (supported types, <=20MB):", len(doc_files))
print("indexable bytes: %.1f MB" % (sum(s for _, s in doc_files) / 1e6))
print("by type:")
for ext, n in Counter(e for e, _ in doc_files).most_common():
    print(f"   {ext:8} {n:7}  {sum(s for e, s in doc_files if e == ext)/1e6:9.1f} MB")
