"""Count the high-value archive subset (documents that carry engineering text)."""
import re, time
from collections import Counter
from pathlib import Path

ROOTS = [Path(r"E:\ENGINEERING_DATA\IHP_Projects"), Path(r"E:\ENGINEERING_DATA\archives")]
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xlsm", ".xls", ".msg", ".pptx", ".txt", ".md", ".csv"}
MAX_BYTES = 20 * 1024 * 1024
WANTED = re.compile(
    r"sow|scope of work|boq|bill of quantit|\bear\b|engineering assessment|\bmom\b|minutes|"
    r"summary|quot|rfq|proposal|icr|wcc|wch|submittal|spec|material|permit|budget|cost estimate|"
    r"method statement|report",
    re.I,
)
SKIP = re.compile(r"drawing|\bdwg\b|as[- ]?built|layout|scan", re.I)

deadline = time.time() + 120
hits = Counter(); hit_bytes = Counter(); n = 0
for root in ROOTS:
    if not root.is_dir():
        continue
    for path in root.rglob("*"):
        if time.time() > deadline:
            print("!! deadline hit (partial)"); break
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        ext = path.suffix.lower()
        if ext not in DOC_EXT or SKIP.search(path.stem):
            continue
        if not WANTED.search(path.stem):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_BYTES:
            continue
        n += 1
        hits[ext] += 1
        hit_bytes[ext] += size

print("high-value docs:", n, "| %.1f MB" % (sum(hit_bytes.values()) / 1e6))
for ext, c in hits.most_common():
    print(f"   {ext:8} {c:6}  {hit_bytes[ext]/1e6:8.1f} MB")
