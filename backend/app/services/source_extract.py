"""Text extraction for the PR data room.

The engineer's raw data arrives in whatever format it was produced in: the PR
form, a utility matrix, the technical specification, drawings, supplier
quotations, emails from the PI, a costing sheet, site photos. Everything is
stored on the project as a *source document* and reduced to text here, so the
AI can read it and the reviewer can see exactly which file said what.

Every function is defensive: an unreadable file returns an empty string plus a
short reason instead of raising, because one bad upload must never break the
data room.
"""

from __future__ import annotations

import csv
import email
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

#: The archive taxonomy the team already files by (E:\ENGINEERING_DATA\IHP_Projects).
TAXONOMY: tuple[dict[str, str], ...] = (
    {"key": "01_Initiation", "label": "01 Initiation - PR form, request"},
    {"key": "02_Budget_Cost", "label": "02 Budget & Cost - BOQ/MTO, quotations"},
    {"key": "03_Specifications", "label": "03 Specifications - EAR, project summary, specs"},
    {"key": "04_Contracts_PO_NTP", "label": "04 Contracts - PO, NTP"},
    {"key": "05_Schedule", "label": "05 Schedule"},
    {"key": "06_PreCon_Reqs", "label": "06 Pre-construction - RAMS, WICF, LUP, safety"},
    {"key": "07_Construction_Data", "label": "07 Construction data - RFI, RFA, MRI"},
    {"key": "08_Handover_Docs", "label": "08 Handover - punch list, WCC, WCH, tech library"},
    {"key": "09_Invoices", "label": "09 Invoices"},
    {"key": "10_Photos", "label": "10 Photos"},
    {"key": "11_Reports", "label": "11 Reports - MOMs, progress, lessons learned"},
    {"key": "99_Unsorted", "label": "99 Unsorted - engineer raw data, emails"},
)

TAXONOMY_KEYS: frozenset[str] = frozenset(entry["key"] for entry in TAXONOMY)

#: What a document *is* (drives the review and the generation).
DOC_TYPES: tuple[str, ...] = (
    "pr_form",
    "raw_data",
    "utility_matrix",
    "technical_specification",
    "drawing",
    "boq",
    "mto",
    "cost_estimate",
    "quotation",
    "email",
    "mom",
    "project_summary",
    "sow",
    "schedule",
    "report",
    "photo",
    "other",
)

#: Hard cap on the text kept per file, so one huge workbook cannot flood the
#: prompt (or the database).
MAX_CHARS = 120_000

_PLAIN_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".log", ".sql"}


def _clip(text: str) -> str:
    text = text.replace("\x00", " ")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + "\n[... truncated ...]"
    return text


def _pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise RuntimeError(f"pdf not readable: {exc}") from exc


def _docx_text(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _xlsx_text(path: Path) -> str:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts: list[str] = []
    try:
        for sheet in workbook.worksheets:
            parts.append(f"# sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                line = " | ".join(cells).rstrip(" |")
                if line.strip():
                    parts.append(line)
    finally:
        workbook.close()
    return "\n".join(parts)


def _soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert_with_soffice(path: Path, target: str) -> Path | None:
    """Convert a file with headless LibreOffice; None when unavailable."""
    soffice = _soffice()
    if not soffice:
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="ihp-conv-"))
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", target, "--outdir", str(out_dir), str(path)],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except Exception:
        return None
    produced = sorted(out_dir.glob(f"*.{target.split(':')[0]}"))
    return produced[0] if produced else None


def _legacy_excel_text(path: Path) -> str:
    """.xls / .xlsb: openpyxl cannot read them - convert to xlsx first."""
    converted = _convert_with_soffice(path, "xlsx")
    if converted is None or not converted.exists():
        raise RuntimeError("old Excel format: no converter available")
    try:
        return _xlsx_text(converted)
    finally:
        shutil.rmtree(converted.parent, ignore_errors=True)


def _pptx_text(path: Path) -> str:
    converted = _convert_with_soffice(path, "pptx")
    if converted is None:
        raise RuntimeError("presentation: no converter available")
    try:
        import zipfile
        import re

        with zipfile.ZipFile(converted) as zf:
            names = sorted(n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
            parts = []
            for name in names:
                xml = zf.read(name).decode("utf-8", "ignore")
                texts = re.findall(r"<a:t>(.*?)</a:t>", xml)
                if texts:
                    parts.append(" ".join(texts))
            return "\n".join(parts)
    finally:
        shutil.rmtree(converted.parent, ignore_errors=True)


def _msg_text(path: Path) -> str:
    import extract_msg

    message = extract_msg.Message(str(path))
    try:
        header = "\n".join(
            part
            for part in (
                f"From: {message.sender}",
                f"To: {message.to}",
                f"Cc: {message.cc}",
                f"Date: {message.date}",
                f"Subject: {message.subject}",
            )
            if part and not part.endswith("None")
        )
        body = message.body or ""
        names = [att.longFilename or att.shortFilename for att in message.attachments]
        if names:
            body += "\n\n[attachments] " + ", ".join(n for n in names if n)
        return header + "\n\n" + body
    finally:
        message.close()


def _eml_text(path: Path) -> str:
    with path.open("rb") as handle:
        message = email.message_from_binary_file(handle)
    parts = [
        f"From: {message.get('From', '')}",
        f"To: {message.get('To', '')}",
        f"Cc: {message.get('Cc', '')}",
        f"Date: {message.get('Date', '')}",
        f"Subject: {message.get('Subject', '')}",
    ]
    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                body += payload.decode(part.get_content_charset() or "utf-8", "ignore")
    else:
        payload = message.get_payload(decode=True) or b""
        body = payload.decode(message.get_content_charset() or "utf-8", "ignore")
    return "\n".join(parts) + "\n\n" + body


def _plain_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() in {".csv", ".tsv"}:
        try:
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows if any(row))
        except Exception:
            return text
    if path.suffix.lower() == ".json":
        try:
            return json.dumps(json.loads(text), indent=2)[:MAX_CHARS]
        except Exception:
            return text
    return text


def extract_text(path: Path) -> tuple[str, str]:
    """Return (text, note). The note explains what happened, never raises."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _pdf_text(path)
        elif suffix == ".docx":
            text = _docx_text(path)
        elif suffix == ".doc":
            converted = _convert_with_soffice(path, "docx")
            if converted is None:
                return "", "legacy .doc: no converter available"
            try:
                text = _docx_text(converted)
            finally:
                shutil.rmtree(converted.parent, ignore_errors=True)
        elif suffix == ".xlsx":
            text = _xlsx_text(path)
        elif suffix in {".xls", ".xlsb"}:
            text = _legacy_excel_text(path)
        elif suffix in {".pptx", ".ppt"}:
            text = _pptx_text(path)
        elif suffix == ".msg":
            text = _msg_text(path)
        elif suffix == ".eml":
            text = _eml_text(path)
        elif suffix in _PLAIN_SUFFIXES:
            text = _plain_text(path)
        elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".dwg", ".dxf", ".zip", ".rar", ".7z", ".mp4", ".mov"}:
            return "", "no text layer (image / drawing / archive) - stored for the reviewer"
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001 - a bad file must not break the room
        return "", f"could not read: {exc}"

    text = _clip(text or "")
    if not text.strip():
        return "", "no text found in the file"
    return text, ""


def excerpt(text: str, limit: int = 400) -> str:
    flat = " ".join(text.split())
    return flat[:limit]
