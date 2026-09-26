"""Parse a KAUST PR request-system export (PDF/DOCX/TXT) into intake fields.

The "Campus and Community Project Request System" details page has a fixed
label/value structure. Exports and copy-pastes vary ("Label | value",
"Label: value", or label and value on separate lines), so parsing is anchored
on the known labels, longest-label-first.
"""

from __future__ import annotations

import io
import re

# (label, field key) — sorted longest-label-first at load so "Location"
# never swallows "Location Details" and "Work Phone/Cell" never swallows
# "End User / Funding Approver Work Phone/Cell".
_LABEL_PAIRS = [
    ("Reference Number", "pr_number"),
    ("Project Request Title", "title"),
    ("Requester Name", "requester_name"),
    ("Requester Email", "requester_email"),
    ("Requester Division", "requester_division"),
    ("Work Phone/Cell", "requester_phone"),
    ("End User / Funding Approver Name", "approver_name"),
    ("End User / Funding Approver Division", "approver_division"),
    ("End User / Funding Approver Email", "approver_email"),
    ("End User / Funding Approver Work Phone/Cell", "approver_phone"),
    ("End User / Funding Approver Executive", "approver_executive"),
    ("Location", "location"),
    ("Location Details", "location_details"),
    ("Source of Funding", "funding_source"),
    ("Has the Project Coordinated with Facilities Management", "fm_coordinated"),
    ("Project Request Description", "description"),
    ("Attachments", "attachments"),
]
LABELS = sorted(_LABEL_PAIRS, key=lambda pair: len(pair[0]), reverse=True)

# Labels that appear in the export but are not mapped — they still terminate
# a multiline value.
STOP_LABELS = {label.lower() for label, _ in LABELS} | {
    "status",
    "initial submission",
    "request details",
}

MULTILINE_FIELDS = {"description", "attachments"}

SUPPORTED_INNER_EXTENSIONS = {"pdf", "docx", "txt", "md"}

#: Matches "PR-12623", "PR 12643", "pr12601" etc.
PR_NUMBER_RE = re.compile(r"\bPR[-\s]?(\d{3,6})\b", re.IGNORECASE)

#: Noise lines swept in from PDF footers / form chrome, not real attachments.
ATTACHMENT_NOISE_RE = re.compile(
    r"^(page\s+\d+\s+of\s+\d+|generated on|request created by|no attachment available)",
    re.IGNORECASE,
)


def normalize_pr_number(text: str) -> str | None:
    """Extract a canonical 'PR-NNNNN' from free text, or None."""
    match = PR_NUMBER_RE.search(text or "")
    return f"PR-{match.group(1)}" if match else None


def title_from_subject(subject: str) -> str | None:
    """Derive a title from an email subject: strip RE:/FW: and the PR token."""
    title = re.sub(r"^(re|fw|fwd)\s*:\s*", "", subject or "", flags=re.IGNORECASE)
    title = PR_NUMBER_RE.sub("", title).strip(" -—|")
    return title or None


def extract_text(filename: str, content: bytes) -> str:
    """Pull raw text out of a .pdf / .docx / .txt / .md PR form export."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == "docx":
        import docx

        document = docx.Document(io.BytesIO(content))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        return "\n".join(parts)
    if ext in {"txt", "md", ""}:
        return content.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: .{ext} (use PDF, DOCX, or TXT)")


def _label_at(line: str) -> tuple[str, str] | None:
    """Return (label, field key) when the line starts with a known label."""
    low = line.lower()
    for label, key in LABELS:
        if low.startswith(label.lower()):
            return label, key
    return None


def parse_pr_form_fields(text: str) -> dict:
    """Parse raw form text into raw fields (attachments as a list)."""
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    fields: dict[str, str | list[str]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        match = _label_at(line)
        if match is None:
            i += 1
            continue
        label, key = match
        if key in fields:  # first occurrence wins
            i += 1
            continue

        # Value may follow the label on the same line ("Label | value") or on
        # the next non-empty line; multiline fields gather until the next label.
        rest = line[len(label):].lstrip(" |:-\t").strip()
        j = i + 1
        if key in MULTILINE_FIELDS:
            gathered = [rest] if rest else []
            while j < len(lines):
                nxt = lines[j]
                if nxt and (_label_at(nxt) is not None or nxt.lower() in STOP_LABELS):
                    break
                if nxt:
                    gathered.append(nxt)
                j += 1
            value = "\n".join(gathered).strip()
        else:
            value = rest
            while not value and j < len(lines):
                nxt = lines[j]
                if not nxt:
                    j += 1
                    continue
                if _label_at(nxt) is not None or nxt.lower() in STOP_LABELS:
                    break
                value = nxt
                j += 1
            value = re.sub(r"\s+", " ", value).strip()

        if key == "attachments":
            # Filenames may contain commas, and PDF footers glued into the
            # list may contain dates with commas — so join fragments until a
            # fragment ending in a file extension is found, then keep only
            # entries that look like filenames.
            merged: list[str] = []
            for frag in re.split(r"[,;\n]", value):
                frag = frag.strip()
                if not frag:
                    continue
                if merged and not re.search(r"\.\w{2,5}$", merged[-1]):
                    merged[-1] = f"{merged[-1]}, {frag}"
                else:
                    merged.append(frag)
            items = [
                a
                for a in merged
                if re.search(r"\.\w{2,5}$", a) and not ATTACHMENT_NOISE_RE.match(a)
            ]
            if items:
                fields[key] = items
        elif value:
            fields[key] = value
        i = j
    return fields


def parse_msg(content: bytes) -> tuple[dict, list[tuple[str, bytes]]]:
    """Parse an Outlook .msg file.

    Returns (fields, carried_attachments). Handles three real cases:
    1. PR-system notification email — the label/value form is in the body.
    2. Email carrying the PR form as an attachment (PDF/DOCX/TXT) — parse
       the first attachment that yields a Reference Number.
    3. Anything else with a PR number in the subject (e.g. a site-visit
       invitation) — fall back to subject-derived PR number + title, keeping
       sender/date as provenance.
    """
    import extract_msg

    msg = extract_msg.Message(io.BytesIO(content))
    subject = (msg.subject or "").strip()
    body = msg.body or ""
    sender = (msg.sender or "").strip()
    date = str(msg.date or "").strip()
    carried: list[tuple[str, bytes]] = []
    for attachment in msg.attachments:
        name = attachment.longFilename or attachment.shortFilename or "attachment"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in SUPPORTED_INNER_EXTENSIONS and attachment.data:
            carried.append((name, attachment.data))

    fields: dict = {}
    if subject:
        fields["msg_subject"] = subject
    if sender:
        fields["msg_sender"] = sender
    if date:
        fields["msg_date"] = date

    body_fields = parse_pr_form_fields(body) if body.strip() else {}
    attachment_fields: dict = {}
    for name, data in carried:
        try:
            candidate = parse_pr_form_fields(extract_text(name, data))
        except Exception:
            continue
        if candidate.get("pr_number"):
            attachment_fields = candidate
            fields["parsed_from_attachment"] = name
            break

    chosen = attachment_fields if attachment_fields.get("pr_number") else body_fields
    fields.update(chosen)

    if not fields.get("pr_number"):
        prn = normalize_pr_number(subject)
        if prn:
            fields["pr_number"] = prn
    if not fields.get("title") and subject:
        title = title_from_subject(subject)
        if title:
            fields["title"] = title
    return fields, carried


def parse_any(filename: str, content: bytes) -> tuple[dict, list[tuple[str, bytes]]]:
    """Route by file type; returns (fields, carried_attachments)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "msg":
        return parse_msg(content)
    return parse_pr_form_fields(extract_text(filename, content)), []


def to_intake(fields: dict) -> dict:
    """Map raw parsed fields onto ProjectCreate fields.

    Fields with no dedicated column yet (requester/approver details, FM
    coordination, attachment list) are preserved in the description text.
    """
    location = fields.get("location") or ""
    details = fields.get("location_details") or ""
    combined_location = ", ".join(part for part in [location, details] if part) or None

    project = {
        "pr_number": fields.get("pr_number"),
        "title": fields.get("title"),
        "location": combined_location,
        "pi_name": fields.get("requester_name"),
        "pi_email": fields.get("requester_email"),
        "funding_source": fields.get("funding_source"),
        "description": _compose_description(fields),
    }
    return {k: v for k, v in project.items() if v}


def _compose_description(fields: dict) -> str | None:
    meta = []
    if fields.get("msg_subject"):
        provenance = f"Source: Outlook message \"{fields['msg_subject']}\""
        if fields.get("msg_sender"):
            provenance += f" from {fields['msg_sender']}"
        if fields.get("msg_date"):
            provenance += f" ({fields['msg_date']})"
        meta.append(provenance)
    if fields.get("parsed_from_attachment"):
        meta.append(f"PR data parsed from attachment: {fields['parsed_from_attachment']}")
    requester_bits = ", ".join(
        b for b in [fields.get("requester_division"), fields.get("requester_phone")] if b
    )
    if fields.get("requester_name") or requester_bits:
        meta.append(f"Requester: {fields.get('requester_name', '')} ({requester_bits})")
    approver_bits = ", ".join(
        b for b in [fields.get("approver_division"), fields.get("approver_phone")] if b
    )
    if fields.get("approver_name") or approver_bits:
        line = f"End User / Funding Approver: {fields.get('approver_name', '')} ({approver_bits})"
        if fields.get("approver_executive"):
            line += f"; Executive: {fields['approver_executive']}"
        meta.append(line)
    if fields.get("fm_coordinated"):
        meta.append(f"Coordinated with Facilities Management: {fields['fm_coordinated']}")

    sections = []
    if meta:
        sections.append(". ".join(m.rstrip(".") for m in meta) + ".")
    if fields.get("description"):
        sections.append(fields["description"])
    if fields.get("attachments"):
        sections.append("Attachments listed on the PR form: " + ", ".join(fields["attachments"]))
    return "\n\n".join(sections) or None
