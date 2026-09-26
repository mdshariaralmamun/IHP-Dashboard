"""Archive folder ingestion — the platform's long-term agent memory.

Admins point the platform at an archive folder on any drive (default
suggestion: the ENGINEERING_DATA raw archive). Scanning walks the tree,
extracts text from every supported document, chunks it, and stores the
chunks in the AI corpus (`source="archive"`). The retrieval layer then
serves those chunks to /api/ai/ask as reference material for future
projects — "how did we do the B3 nitrogen line in 2024?" etc.

Incremental + idempotent: a sidecar state file (data/archive_state.json)
records each ingested file's size and mtime. Unchanged files are skipped
on re-scan; changed files are re-ingested; deleted files are left in the
corpus (explicit admin action, never automatic deletion).

Supported formats: .txt .md .log .csv .json | .pdf | .docx | .xlsx .xlsm |
.msg. Everything else is counted as skipped_unsupported.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai.corpus import chunk_text
from ..models import CorpusChunk, CorpusDocument, User

TEXT_EXTS = {".txt", ".md", ".log", ".csv", ".json"}
SUPPORTED_EXTS = TEXT_EXTS | {".pdf", ".docx", ".xlsx", ".xlsm", ".msg"}

MAX_FILE_BYTES = 20 * 1024 * 1024  # skip files larger than 20 MB
MAX_XLSX_ROWS = 5000  # cap spreadsheet rows ingested per file

_state_path: Path | None = None


def _state_file() -> Path:
    global _state_path
    if _state_path is None:
        from ..core.config import get_settings

        data_dir = Path(get_settings().DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)
        _state_path = data_dir / "archive_state.json"
    return _state_path


def _load_state() -> dict[str, Any]:
    if not _state_file().exists():
        return {"files": {}, "last_scan": None}
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"files": {}, "last_scan": None}


def _save_state(state: dict[str, Any]) -> None:
    _state_file().write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Text extraction per format
# ---------------------------------------------------------------------------


def _extract_plain(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — one bad page shouldn't kill the file
            continue
    return "\n".join(pages)


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts: list[str] = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append("\t".join(cells))
    return "\n".join(parts)


def _extract_xlsx(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"### Sheet: {ws.title}")
        for row_count, row in enumerate(ws.iter_rows(values_only=True)):
            if row_count >= MAX_XLSX_ROWS:
                lines.append(f"(… truncated at {MAX_XLSX_ROWS} rows)")
                break
            cells = [str(v) for v in row if v is not None and str(v).strip()]
            if cells:
                lines.append("\t".join(cells))
    wb.close()
    return "\n".join(lines)


def _extract_msg(path: Path) -> str:
    import extract_msg

    msg = extract_msg.Message(str(path))
    try:
        header = f"From: {msg.sender or '?'}\nTo: {msg.to or '?'}\nSubject: {msg.subject or '?'}\nDate: {msg.date or '?'}"
        body = msg.body or ""
        attachments = ", ".join(a.longFilename or a.shortFilename or "?"
                                for a in (msg.attachments or []))
        tail = f"\nAttachments: {attachments}" if attachments else ""
        return f"{header}\n\n{body}{tail}"
    finally:
        msg.close()


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".xlsx": _extract_xlsx,
    ".xlsm": _extract_xlsx,
    ".msg": _extract_msg,
}


def extract_file_text(path: Path) -> str:
    """Extract plain text from a supported file. Raises on unreadable input."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return _extract_plain(path)
    extractor = _EXTRACTORS.get(ext)
    if extractor is None:
        raise ValueError(f"Unsupported file type: {ext}")
    return extractor(path)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def scan_archive(
    root: Path,
    db: Session,
    user: User,
    max_files: int = 1000,
) -> dict[str, Any]:
    """Walk `root` and ingest supported documents into the corpus."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    state = _load_state()
    files_state: dict[str, Any] = state.setdefault("files", {})

    started = time.time()
    seen = ingested = skipped_unchanged = skipped_unsupported = failed = 0
    bytes_total = 0
    by_type: dict[str, int] = {}
    errors: list[dict[str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        seen += 1
        ext = path.suffix.lower()
        rel = path.relative_to(root).as_posix()

        if ext not in SUPPORTED_EXTS:
            skipped_unsupported += 1
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            skipped_unsupported += 1
            errors.append({"file": rel, "error": "file too large (>20 MB)"})
            continue
        if ingested >= max_files:
            errors.append({"file": rel, "error": "max_files reached — re-run to continue"})
            break

        stat = path.stat()
        fingerprint = {"size": stat.st_size, "mtime": stat.st_mtime}
        prior = files_state.get(rel)
        if prior and prior.get("size") == fingerprint["size"] and prior.get("mtime") == fingerprint["mtime"]:
            skipped_unchanged += 1
            continue

        try:
            text = extract_file_text(path)
        except Exception as e:  # noqa: BLE001 — record and move on
            failed += 1
            errors.append({"file": rel, "error": str(e)[:200]})
            continue

        chunks = chunk_text(text) if text.strip() else []
        if not chunks:
            failed += 1
            errors.append({"file": rel, "error": "no extractable text"})
            continue

        # Replace a previous version of this file if it changed.
        if prior and prior.get("doc_id"):
            db.execute(delete(CorpusChunk).where(CorpusChunk.document_id == prior["doc_id"]))
            db.execute(delete(CorpusDocument).where(CorpusDocument.id == prior["doc_id"]))

        doc = CorpusDocument(
            filename=f"archive/{rel}"[:300],
            source="archive",
            chunk_count=len(chunks),
            uploaded_by_id=user.id,
        )
        db.add(doc)
        db.flush()
        for idx, text_chunk in enumerate(chunks):
            db.add(CorpusChunk(
                document_id=doc.id,
                chunk_index=idx,
                text=text_chunk,
                project_id=None,
            ))
        db.commit()

        files_state[rel] = {**fingerprint, "doc_id": doc.id}
        ingested += 1
        bytes_total += stat.st_size
        by_type[ext] = by_type.get(ext, 0) + 1

    state["last_scan"] = {
        "root": str(root),
        "at": datetime.now(timezone.utc).isoformat(),
        "seen": seen,
        "ingested": ingested,
        "skipped_unchanged": skipped_unchanged,
        "skipped_unsupported": skipped_unsupported,
        "failed": failed,
        "by_type": by_type,
        "duration_s": round(time.time() - started, 2),
    }
    _save_state(state)

    return {
        "root": str(root),
        "seen": seen,
        "ingested": ingested,
        "skipped_unchanged": skipped_unchanged,
        "skipped_unsupported": skipped_unsupported,
        "failed": failed,
        "bytes": bytes_total,
        "by_type": by_type,
        "errors": errors[:50],
        "duration_s": round(time.time() - started, 2),
        "last_scan": state["last_scan"],
    }


def archive_status() -> dict[str, Any]:
    """Last scan summary + current corpus stats for the settings UI."""
    state = _load_state()
    return {
        "last_scan": state.get("last_scan"),
        "tracked_files": len(state.get("files", {})),
    }
