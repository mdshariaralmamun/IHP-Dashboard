"""The AI reading of a PR data room ("project brief").

Where the document review (ai/review.py) hunts for what is WRONG, this builds
the structured picture the generators need: the scope split by trade, the
utility matrix (what the site already has, what has to be brought in), the
line items the BOQ/MTO are built from, and the open technical questions that
must be answered before anything is issued.

It only ever reads what the files actually say. Anything the files do not
settle becomes an open question - never an invented value.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import Project, SourceDocument
from . import provider
from .review import escape_control_chars, strip_fences

#: Same character budgets as the review: one huge workbook must not crowd out
#: the rest of the data room.
MAX_CHARS_PER_DOCUMENT = 6000
MAX_DOCUMENT_CHARS = 48000

BRIEF_SYSTEM = (
    "You are the lead engineer for the KAUST IHP (In-House Projects) team. "
    "You read everything the engineer, the PI and the suppliers sent for one "
    "PR and turn it into the structured picture the team builds the MOM, the "
    "Project Summary (EAR), the Scope of Work, the BOQ and the MTO from.\n\n"
    "Rules:\n"
    "- Use ONLY what the files and the project facts say. If a value is not in "
    "the files, do not invent it: put the question in open_questions.\n"
    "- Separate what the PI WANTS (requirement) from what the SITE ALLOWS "
    "(site_check): existing services, spare capacity, tie-in points, "
    "structural limits, shutdown windows.\n"
    "- Name every utility both ways: what the project needs, and whether the "
    "site already has it. A utility that exists is 'excluded' from the new "
    "scope; anything not available has to be provided.\n"
    "- Line items are the take-off: one row per material or activity, with the "
    "unit and quantity exactly as the source gives them. Never merge two "
    "different materials into one row, and keep the source reference.\n"
    "- Open questions are the technical queries: what a supplier must confirm, "
    "what the PI must decide, what O&M must verify. Mark blocking=true when "
    "work cannot start without the answer.\n\n"
    "Answer with ONE JSON object and nothing else:\n"
    "{\n"
    '  "summary": "2-4 sentences: what was asked, and what the site allows",\n'
    '  "scope_by_trade": [{"trade": "Architectural|Electrical|Plumbing|HVAC|'
    'Telecommunication|Fire|General", "requirement": "what is asked for", '
    '"site_check": "what the site allows / blocks", "existing_utilities": '
    '["..."], "excluded": ["what exists and is therefore out of scope"], '
    '"assumptions": ["..."], "source_files": ["..."]}],\n'
    '  "utilities": [{"name": "Nitrogen|Power|Water|Drain|Exhaust|...", '
    '"required": "what the project needs", "available_at_site": "yes|no|'
    'unknown", "evidence": "file or sheet that says so", "action": "what to '
    'do about it"}],\n'
    '  "line_items": [{"ref": "1.1", "trade": "...", "description": "...", '
    '"spec": "make / model / standard", "unit": "EA|L.M.|LOT|BOX|m2", '
    '"qty": "18", "supplier": "...", "source_file": "..."}],\n'
    '  "open_questions": [{"question": "...", "why": "...", "who_can_answer": '
    '"PI|Supplier|O&M|Planner", "blocking": true}],\n'
    '  "documents_seen": [{"file": "...", "kind": "...", "gist": "one line"}],\n'
    '  "missing_documents": ["a document that should exist and does not"],\n'
    '  "risks": ["..."],\n'
    '  "confidence": "high|medium|low"\n'
    "}"
)


def project_facts(project: Project) -> str:
    lines = [
        f"- PR number: {project.pr_number}",
        f"- Title: {project.title}",
        f"- Location: {project.location or 'not stated'}",
        f"- PI / requestor: {project.pi_name or 'not stated'}",
        f"- Current stage: {project.stage}",
    ]
    if project.disposition:
        lines.append(f"- Disposition: {project.disposition}")
    if project.description:
        lines.append(f"- Intake description: {project.description[:1500]}")
    return "\n".join(lines)


def build_prompt(project: Project, sources: list[SourceDocument], texts: dict[int, str]) -> str:
    parts = [
        "== PROJECT FACTS (live register) ==",
        project_facts(project),
        "",
        "== DATA ROOM ==",
    ]
    if not sources:
        parts.append("No files have been uploaded for this PR yet.")
        return "\n".join(parts)
    budget = MAX_DOCUMENT_CHARS
    for source in sources:
        text = (texts.get(source.id) or "").strip()
        if not text:
            parts.append(f"--- {source.filename} [{source.doc_type}] : NO TEXT EXTRACTED ---")
            continue
        keep = min(len(text), MAX_CHARS_PER_DOCUMENT, max(budget, 500))
        budget -= keep
        parts += [
            f"--- {source.filename} [{source.doc_type}, {source.category}] ---",
            text[:keep],
            "",
        ]
        if budget <= 0:
            parts.append("[... remaining files omitted for length ...]")
            break
    return "\n".join(parts)


def parse_brief(raw: str) -> dict[str, Any]:
    """Tolerant JSON parse: fences, control characters, one repair attempt."""
    text = escape_control_chars(strip_fences(raw)).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in the model answer")
    return json.loads(text[start : end + 1])


def run_brief(
    project: Project,
    sources: list[SourceDocument],
    texts: dict[int, str],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Ask the model for the brief. Raises RuntimeError when unreadable."""
    prompt = build_prompt(project, sources, texts)
    answer = provider.chat(
        [{"role": "user", "content": prompt}], system=BRIEF_SYSTEM, model=model
    )
    if not answer:
        raise RuntimeError(
            "The AI provider returned nothing - check the provider and API key "
            "in Settings."
        )
    try:
        return parse_brief(answer)
    except (ValueError, json.JSONDecodeError):
        # One repair round, same as the document review.
        repaired = provider.chat(
            [
                {
                    "role": "user",
                    "content": (
                        "Your previous answer was not valid JSON. Return the SAME "
                        "content as one valid JSON object, nothing else. Here it "
                        "is:\n\n" + answer[:20000]
                    ),
                }
            ],
            system=BRIEF_SYSTEM,
            model=model,
        )
        if not repaired:
            raise RuntimeError("The model answer could not be parsed as JSON.")
        return parse_brief(repaired)
