"""Extract TEXT from the high-value archive documents into a mirror tree of .txt files.

Why: the engineering archive holds ~3,161 engineering documents (SOW, BOQ, EAR,
MOM, schedules, quotations) but they are 5.4 GB of PDF/XLSX/DOCX spread over a
473 GB drive. The AI only needs the text, so this writes a compact text mirror
that can be shipped to the server and indexed into the retrieval corpus.

- resumable: an existing output .txt is skipped
- parallel: one worker per CPU minus two
- skips scanned drawings / empty text layers (no text = nothing to index)
- writes a manifest with per-file status
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOTS = [Path(r"E:\ENGINEERING_DATA\IHP_Projects"), Path(r"E:\ENGINEERING_DATA\archives")]
OUT = Path(r"E:\IHP_AI_CORPUS")
MANIFEST = Path(r"E:\IHP_AI_CORPUS_manifest.json")
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xlsm", ".xls", ".msg", ".pptx", ".txt", ".md", ".csv"}
MAX_BYTES = 20 * 1024 * 1024
MIN_CHARS = 250
WANTED = re.compile(
    r"sow|scope of work|boq|bill of quantit|\bear\b|engineering assessment|\bmom\b|minutes|"
    r"summary|quot|rfq|proposal|icr|wcc|wch|submittal|spec|material|permit|budget|cost estimate|"
    r"method statement|report",
    re.I,
)
SKIP = re.compile(r"drawing|\bdwg\b|as[- ]?built|layout|scan", re.I)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def extract(path: Path) -> tuple[str, str]:
    """Return (text, error). Text is "" when nothing was extracted."""
    ext = path.suffix.lower()
    try:
        if ext in {".txt", ".md", ".csv"}:
            return path.read_text(encoding="utf-8", errors="replace"), ""
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(pages), ""
        if ext == ".docx":
            import docx
            document = docx.Document(str(path))
            parts = [p.text for p in document.paragraphs if p.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append("\t".join(cells))
            return "\n".join(parts), ""
        if ext in {".xlsx", ".xlsm", ".xls"}:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            lines = []
            for ws in wb.worksheets:
                lines.append("### Sheet: " + str(ws.title))
                for idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if idx >= 4000:
                        lines.append("(... truncated)")
                        break
                    cells = [str(v) for v in row if v is not None and str(v).strip()]
                    if cells:
                        lines.append("\t".join(cells))
            wb.close()
            return "\n".join(lines), ""
        if ext == ".msg":
            import extract_msg
            msg = extract_msg.Message(str(path))
            try:
                return f"{msg.sender}\n{msg.subject}\n{msg.date}\n\n{msg.body or ''}", ""
            finally:
                msg.close()
        if ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(str(path))
            parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        parts.append(shape.text)
            return "\n".join(parts), ""
        if ext == ".doc":
            return "", "legacy .doc not supported"
    except Exception as exc:  # noqa: BLE001
        return "", type(exc).__name__ + ": " + str(exc)[:180]
    return "", "unsupported"


def _job(path_str: str) -> dict:
    path = Path(path_str)
    rel = None
    for root in ROOTS:
        try:
            rel = path.relative_to(root)
            break
        except ValueError:
            continue
    if rel is None:
        return {"file": path_str, "status": "outside"}
    out_file = OUT / (str(rel) + ".txt")
    if out_file.exists() and out_file.stat().st_size > 0:
        return {"file": str(rel), "status": "cached", "chars": out_file.stat().st_size}
    text, error = extract(path)
    if error:
        return {"file": str(rel), "status": "error", "error": error}
    text = text.strip()
    if len(text) < MIN_CHARS:
        return {"file": str(rel), "status": "no_text", "chars": len(text)}
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(text, encoding="utf-8")
    return {"file": str(rel), "status": "ok", "chars": len(text)}


def main() -> None:
    targets: list[str] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
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
                if path.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            targets.append(str(path))

    print(f"targets: {len(targets)}", flush=True)
    workers = max(2, (os.cpu_count() or 4) - 2)
    print(f"workers: {workers}", flush=True)
    started = time.time()
    results: list[dict] = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, t) for t in targets]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                results.append({"file": "?", "status": "error", "error": str(exc)[:150]})
            done += 1
            if done % 100 == 0:
                ok = sum(1 for r in results if r["status"] == "ok")
                chars = sum(r.get("chars", 0) for r in results if r["status"] == "ok")
                print(
                    f"  {done}/{len(targets)}  ok={ok}  ~{chars/1e6:.1f}M chars  "
                    f"{time.time()-started:.0f}s",
                    flush=True,
                )

    summary = {
        "targets": len(targets),
        "by_status": {},
        "chars": sum(r.get("chars", 0) for r in results if r["status"] == "ok"),
        "seconds": round(time.time() - started, 1),
        "errors": [r for r in results if r["status"] == "error"][:200],
    }
    for r in results:
        summary["by_status"][r["status"]] = summary["by_status"].get(r["status"], 0) + 1
    MANIFEST.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["by_status"], indent=2), flush=True)
    print(f"chars: {summary['chars']/1e6:.1f}M  seconds: {summary['seconds']}", flush=True)
    print("manifest:", MANIFEST, flush=True)


if __name__ == "__main__":
    main()