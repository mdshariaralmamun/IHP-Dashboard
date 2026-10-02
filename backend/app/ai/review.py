"""Per-project AI review of the documents the team uploaded.

Everything a PR carries - the request form, the equipment technical
specification, the utility matrix, the invitation, drawings, calculations and
the BOQ/MTO - is already text-extracted into the corpus, scoped to its project
(services/app_documents.py). This module reads that text together with the
live project facts and asks the model for one structured review:

  * what the request actually is, in two sentences;
  * what each document is and what it contributes;
  * the scope of work by trade (the raw material an EAR / SOW draft is built
    from);
  * the QUESTIONS the engineer has to answer;
  * and above all the CONFLICTS - two documents that disagree, a design
    deficiency, an arithmetic error, a missing input - each with a severity,
    the documents involved, why it matters and what has to be fixed.

Conflicts are the point, so the prompt is built around them: the reviewer is
told to treat anything it cannot verify against the documents as a question
rather than a fact. A model misreads numbers; naming the document, quoting the
reason and leaving the resolution to the engineer is what makes the output
safe to act on.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CorpusChunk, CorpusDocument, Project
from . import provider

#: How much document text to put in one prompt. The configured model has an
#: 8k-token context shared with the answer, so this is a character budget that
#: keeps the request inside it.
MAX_DOCUMENT_CHARS = 14000
#: Per-document ceiling, so one huge workbook cannot crowd out the rest.
MAX_CHARS_PER_DOCUMENT = 6000

#: Document kinds we can name from a filename. The model still reads the text;
#: this only tells it how to read the file, and it is reported back so the
#: reviewer can be corrected by renaming.
_KIND_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("utility_matrix", ("utility matrix", "utility-matrix", "utilitymatrix", "utility")),
    ("pr_form", ("pr form", "pr request", "request form", "intake form", "pr-", "pr_")),
    ("equipment_spec", ("spec", "datasheet", "data sheet", "technical")),
    ("invitation", ("invitation", "meeting invite", ".eml", ".msg", "calendar")),
    ("calculation", ("calc", "sizing", "load", "heat", "pressure drop")),
    ("drawing", ("drawing", "dwg", "layout", "p&id", "pid", "plan", "sketch")),
    ("boq", ("boq", "bill of quantit", "mto", "take off", "take-off")),
)

SEVERITIES = ("critical", "major", "minor", "info")

REVIEW_SYSTEM = (
    "You are the senior engineering reviewer for the KAUST IHP (In-House "
    "Projects) team. You review the documents attached to a project request "
    "before the team commits to a scope of work.\n\n"
    "Your job is to find what is WRONG or MISSING, not to be agreeable.\n\n"
    "Rules:\n"
    "- Only use what the documents and the project facts actually say. Never "
    "invent a value, a clause, a standard number or a document.\n"
    "- A conflict is two sources that disagree (a utility matrix says 6 bar, "
    "the specification says 10 bar), or a document that contradicts itself.\n"
    "- A deficiency is a design gap: a missing input, an undefined duty, a "
    "calculation that cannot be checked from the data given, a load with no "
    "support, an equipment rating below the stated duty.\n"
    "- Judge the arithmetic: recompute the sums, flow rates and conversions "
    "you CAN check from the documents, and report any mismatch with both "
    "numbers.\n"
    "- Severity: critical = cannot proceed or unsafe; major = will cause "
    "rework or an RFI; minor = tidy-up; info = context worth knowing.\n"
    "- Every finding must name the document(s) it comes from and say what has "
    "to be fixed. If you cannot point at a document, make it a question "
    "instead of a finding.\n"
    "- Return STRICT JSON only. No prose, no markdown fences."
)

REVIEW_INSTRUCTION = (
    "Review this project request and its documents.\n\n"
    "Return JSON with exactly this shape:\n\n"
    "{\n"
    '  "summary": "two sentences: what is being requested and why",\n'
    '  "documents": [{"name": "file name", "kind": "pr_form|equipment_spec|'
    'utility_matrix|invitation|calculation|drawing|boq|other", "gist": "one '
    'line: what this document contributes"}],\n'
    # ONE row per scope line, not a nested array: the nested shape is where
    # the model produced unbalanced brackets in production. The rows are
    # grouped into trades here, so the report shape is unchanged.
    '  "scope_by_trade": [{"trade": "Civil/Architectural|Plumbing|HVAC|'
    'Electrical|General", "item": "one specific scope line"}],\n'
    '  "deliverables": ["what the team must produce or buy"],\n'
    '  "findings": [{"id": "F1", "severity": "critical|major|minor|info", '
    '"kind": "conflict|deficiency|calculation|missing_input|unclear", '
    '"title": "short title", "documents": ["file name"], '
    '"detail": "what the documents say, quoted where it matters", '
    '"why": "why this is a problem for the design or the construction", '
    '"required_fix": "the specific action that closes it"}],\n'
    '  "questions": ["a question only the requester or the designer can '
    'answer"],\n'
    '  "confidence": "high|medium|low",\n'
    '  "missing_documents": ["a document that should have been attached and '
    'was not"],\n'
    '  "unread_documents": ["a file listed under ATTACHED BUT NOT READABLE"]\n'
    "}\n\n"
    "Every string must fit on one line: no raw line breaks inside a string, "
    "no trailing commas, and no array nested directly inside another array."
)


def guess_kind(filename: str) -> str:
    """Name a document from its filename, for the prompt and the report."""
    lowered = (filename or "").lower()
    for kind, needles in _KIND_PATTERNS:
        if any(needle in lowered for needle in needles):
            return kind
    return "other"


def review_path(project: Project) -> Path:
    from ..services import storage

    return storage.project_dir(project.pr_number, "ai") / "review.json"


def load_review(project: Project) -> dict[str, Any] | None:
    path = review_path(project)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_review(project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    path = review_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def project_documents(
    db: Session, project: Project, *, max_chars: int = MAX_DOCUMENT_CHARS,
) -> list[dict[str, str]]:
    """The project's ingested documents, oldest first, as one text block each.

    Only documents already indexed are returned: indexing is a slow,
    provider-bound job, and the review reports what it actually read rather
    than pretending a file was considered.
    """
    docs = db.scalars(
        select(CorpusDocument)
        .where(CorpusDocument.project_id == project.id)
        .order_by(CorpusDocument.id)
    ).all()
    out: list[dict[str, str]] = []
    budget = max_chars
    for doc in docs:
        if budget <= 0:
            break
        chunks = db.scalars(
            select(CorpusChunk)
            .where(CorpusChunk.document_id == doc.id)
            .order_by(CorpusChunk.chunk_index)
        ).all()
        text = "\n".join(chunk.text for chunk in chunks).strip()
        if not text:
            continue
        allowed = min(MAX_CHARS_PER_DOCUMENT, budget)
        clipped = text[:allowed]
        if len(text) > allowed:
            clipped += "\n[... truncated for this review ...]"
        name = doc.filename.replace("attachment/", "", 1)
        out.append({"name": name, "kind": guess_kind(name), "text": clipped})
        budget -= len(clipped)
    return out


def strip_fences(raw: str) -> str:
    """Drop the markdown fence a model wraps JSON in."""
    text = (raw or "").strip()
    fence = re.search(r"\x60\x60\x60(?:json)?\s*(.+?)\x60\x60\x60", text, re.S)
    return fence.group(1).strip() if fence else text


def escape_control_chars(text: str) -> str:
    """Escape raw newlines/tabs INSIDE strings, which JSON forbids.

    A long answer quoting a document almost always contains one, and it is the
    most common reason a hand-rolled parser sees "Expecting ',' delimiter".
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if not in_string:
            if char == '"':
                in_string = True
            out.append(char)
            continue
        if escaped:
            escaped = False
            out.append(char)
        elif char == "\\":
            escaped = True
            out.append(char)
        elif char == '"':
            in_string = False
            out.append(char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20:
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def _normalise(data: dict) -> dict[str, Any]:
    """Fill the gaps and group the flat scope rows back into trades."""
    for key, default in (
        ("summary", ""), ("documents", []), ("scope_by_trade", []),
        ("deliverables", []), ("findings", []), ("questions", []),
        ("missing_documents", []), ("unread_documents", []),
        ("confidence", "low"),
    ):
        data.setdefault(key, default)

    grouped: dict[str, list[str]] = {}
    for row in data.get("scope_by_trade") or []:
        if isinstance(row, dict) and "item" in row:
            grouped.setdefault(str(row.get("trade") or "General"), []).append(
                str(row["item"])
            )
        elif isinstance(row, dict) and isinstance(row.get("items"), list):
            grouped.setdefault(str(row.get("trade") or "General"), []).extend(
                str(item) for item in row["items"]
            )
    if grouped:
        data["scope_by_trade"] = [
            {"trade": trade, "items": items} for trade, items in grouped.items()
        ]

    for finding in data["findings"]:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "minor").lower()
        finding["severity"] = severity if severity in SEVERITIES else "minor"
        finding.setdefault("documents", [])
    return data


def parse_review(raw: str) -> dict[str, Any]:
    """Tolerant JSON extraction.

    Models fence, pad, quote and - in production - emit the odd unbalanced
    bracket inside a nested array. Rather than fail the whole review, try the
    answer as-is and then with the mechanical defects repaired.
    """
    text = strip_fences(raw)
    attempts = [text]
    repaired = escape_control_chars(re.sub(r",(\s*[}\]])", r"\1", text))
    if repaired != text:
        attempts.append(repaired)

    for candidate in attempts:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return _normalise(data)
    raise ValueError("the model did not return valid JSON")


def unread_attachments(
    project: Project, documents: list[dict[str, str]],
) -> list[str]:
    """Files on the project that the review could not read.

    They must not be reported as MISSING: the difference between "nobody
    attached it" and "it is attached but not indexed" is what tells the team
    whether to chase the requester or press the index button.
    """
    read = {doc["name"].lower() for doc in documents}
    return [
        attachment.filename
        for attachment in project.attachments
        if attachment.filename.lower() not in read
    ]


def project_facts(project: Project, derived: dict[str, Any]) -> str:
    """The live register row, so the review can spot a tracker/document clash."""
    rows = [
        ("PR number", project.pr_number),
        ("Title", project.title),
        ("Stage", project.stage),
        ("Location", project.location),
        ("PI", project.pi_name),
        ("Planner bucket", project.planner_bucket),
        ("Division", derived.get("division") or derived.get("phase")),
        ("Type", derived.get("project_type")),
        ("Trades", ", ".join(derived.get("trades") or []) or None),
        ("Priority", derived.get("priority")),
        ("Requestor", derived.get("requestor")),
        ("Assigned to", derived.get("assigned_to")),
        ("Execution lead", derived.get("execution_lead")),
        ("Start", derived.get("start_date")),
        ("Finish", derived.get("finish_date")),
        ("Latest status", derived.get("latest_status")),
    ]
    return "\n".join(f"- {label}: {value}" for label, value in rows if value)


def build_prompt(
    project: Project,
    derived: dict[str, Any],
    documents: list[dict[str, str]],
    unread: list[str] | None = None,
) -> str:
    parts = [
        REVIEW_INSTRUCTION,
        "",
        "== PROJECT FACTS (live register) ==",
        project_facts(project, derived),
    ]
    if project.description:
        parts += ["", "== PROJECT DESCRIPTION / NOTES ==", project.description[:2000]]
    if documents:
        parts += ["", "== DOCUMENTS =="]
        for doc in documents:
            parts += [f"--- {doc['name']} (kind: {doc['kind']}) ---", doc["text"], ""]
    else:
        parts += [
            "",
            "== DOCUMENTS ==",
            "None have been indexed yet. Review only what the project facts",
            "contain, and do NOT list files below as missing_documents.",
        ]
    if unread:
        parts += [
            "",
            "== ATTACHED BUT NOT READABLE BY YOU ==",
            "These files exist on the project but could not be read (not indexed,",
            "or a format with no text). They are NOT missing: never claim their",
            "contents and never list them under missing_documents. List them under",
            "unread_documents instead.",
            *(f"- {name}" for name in unread),
        ]
    return "\n".join(parts)


def critical_count(payload: dict[str, Any]) -> int:
    return sum(
        1 for finding in payload.get("findings") or []
        if isinstance(finding, dict) and finding.get("severity") == "critical"
    )


def run_review(
    db: Session, project: Project, derived: dict[str, Any],
    *, model: str | None = None,
) -> dict[str, Any]:
    """Ask the model for the review and persist it next to the project.

    Raises RuntimeError with a message the endpoint can surface: an unreadable
    answer is a failed review, never a silently empty one.
    """
    documents = project_documents(db, project)
    unread = unread_attachments(project, documents)
    prompt = build_prompt(project, derived, documents, unread)
    raw = provider.chat(
        [{"role": "user", "content": prompt}], system=REVIEW_SYSTEM, model=model
    )
    if not raw:
        raise RuntimeError(
            "The AI provider returned nothing - check the provider and API key "
            "in Settings."
        )
    try:
        payload = parse_review(raw)
    except (ValueError, json.JSONDecodeError) as first_error:
        # One repair round. A model that emits one bad bracket should not cost
        # the whole review - it is asked to return the same content, valid.
        repaired = provider.chat(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": raw[:6000]},
                {
                    "role": "user",
                    "content": (
                        f"That JSON is invalid ({first_error}). Return the SAME "
                        "review as valid JSON only: every string on one line, no "
                        "trailing commas, no array nested directly inside another "
                        "array."
                    ),
                },
            ],
            system=REVIEW_SYSTEM,
            model=model,
        )
        try:
            if not repaired:
                raise ValueError(str(first_error))
            payload = parse_review(repaired)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"The AI review could not be read, even after asking the model "
                f"to correct it ({exc})."
            ) from exc

    # A finding may only cite a document the reviewer actually read; anything
    # else is flagged rather than presented as evidence.
    read_names = {doc["name"].lower() for doc in documents}
    for finding in payload.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        finding["documents_unverified"] = [
            str(name)
            for name in finding.get("documents") or []
            if str(name).lower() not in read_names
        ]

    payload["project_id"] = project.id
    payload["pr_number"] = project.pr_number
    payload["model"] = model or ""
    payload["documents_read"] = [
        {"name": doc["name"], "kind": doc["kind"]} for doc in documents
    ]
    payload["documents_indexed"] = len(documents)
    payload["critical_count"] = critical_count(payload)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return save_review(project, payload)
