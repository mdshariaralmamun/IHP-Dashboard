"""The Project Delivery Assistant: the app's own generators, driven in gate order.

The assistant is not a second implementation of the workflow. It is a small
state machine over the things that already exist:

* the five-stage spine and its gates live in app/api/pipeline.py, and are
  imported here so there is exactly one set of rules;
* the EAR funnel runs beside the spine (project.ear.status), never inside it;
* MOM, Project Summary, EAR, SOW, BOQ, MTO documents come from the real
  generators (services/docgen.py, summary_docgen.py, ear_docgen.py,
  sow_boq_mto_docgen.py) and land in the same storage and the same panels;
* the Procore binder is the existing combined_binder(), including the comment
  log;
* the language comes from app/ai/provider.py, so DeepSeek today and Ollama
  tomorrow behave the same.

Two rules shape every call:

1. **Nothing is written without an explicit action.** propose() only records
   what the team pasted and says which step comes next; run_action() is the
   only thing that writes, and it refuses (GateBlocked) when the pipeline gate
   says the step is not allowed yet.
2. **Labour is in-house.** No writer ever puts manpower cost into a total:
   EAR trade inputs always carry estimated_manpower_cost = 0.0, BOQ lines are
   unpriced, and the assessment prints the $0.00 labour line.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import provider
from ..core.config import get_settings
from ..models import (
    AssistantMessage,
    BoqMtoItem,
    EarRecord,
    EarTradeInput,
    MomRecord,
    Project,
    SowRecord,
    User,
)
from . import docgen, ear_docgen, emailer, storage, workflow
from . import sow_boq_mto_docgen as generators

#: The labour line every cost view must print (IHP works in-house).
LABOUR_LINE = "Labor: IHP In-House Resources \u2014 $0.00 (Covered by IHP)"

#: Everything is Supply & Install by IHP; the assistant must say so.
BASIS = "Supply & Install by IHP"

#: Warn (and report elapsed_ms) past this; the request is refused past the hard cap.
SOFT_BUDGET_S = 60
HARD_BUDGET_S = 90

MAX_MESSAGE_CHARS = 20000

#: The six canonical trade groups, in SOW section 3.1 order (A, B, E, C, D, F).
TRADE_NAMES: dict[str, str] = {code: name for code, name, _a in generators.TRADE_GROUPS}
SOW_ORDER: list[str] = [code for _sec, _name, code in generators.SOW_SECTION_ORDER]

#: Pipeline statuses that mean "the package has left the building".
ISSUED = ("approved", "pending_approval")


class GateBlocked(Exception):
    """Raised when the pipeline gate refuses the action. The API turns it into 409."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pipeline_api():
    """Lazy import: the gates live in the API layer, not here."""
    from ..api import pipeline as pipeline_api

    return pipeline_api


def _mom_api():
    from ..api import mom as mom_api

    return mom_api


def trades_in_sow_order() -> list[tuple[str, str]]:
    """[(code, name)] in the SOW section order the document uses."""
    return [(code, TRADE_NAMES.get(code, code)) for code in SOW_ORDER]


def artifact(kind: str, label: str, filename: str | None = None, url: str | None = None,
             panel: str | None = None, meta: dict | None = None) -> dict:
    return {
        "kind": kind,
        "label": label,
        "filename": filename,
        "url": url,
        "panel": panel,
        "meta": meta or {},
    }


# ---------------------------------------------------------------------------
# The action registry
# ---------------------------------------------------------------------------
#: precondition values: None | "mom_confirmed" | "stage2_out" | "stage3_out"
#:                      | "sow_exists" | "procore_approved" | "ear_exists" | "ear_pi"


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    track: str            # "spine" | "ear"
    stage: int
    capability: str
    panel: str
    audit_key: str
    precondition: str | None = None
    writer: Callable[..., dict] | None = None
    instruction: str = ""  # what the model must return in data


ACTIONS: dict[str, Action] = {}


def _register(action: Action) -> Action:
    ACTIONS[action.id] = action
    return action


def _latest_sow(db: Session, project: Project) -> SowRecord | None:
    return db.scalars(
        select(SowRecord).where(SowRecord.project_id == project.id).order_by(SowRecord.id.desc())
    ).first()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def pipeline_state(db: Session, project: Project) -> dict:
    api = _pipeline_api()
    return api._payload(api._rows(db, project.id))


def ear_state(db: Session, project: Project) -> dict:
    """The EAR funnel: a parallel track, reported next to the spine."""
    ear = project.ear
    if ear is None:
        return {"status": "not_started", "next_step": "ear.draft", "trade_inputs": 0, "parallel": True}
    following = {
        "draft": "ear.pi_signature",
        "pi_signature": "ear.asepc",
        "asepc_pending": None,
    }.get(ear.status or "draft")
    return {
        "status": ear.status or "draft",
        "next_step": following,
        "trade_inputs": len(ear.trade_inputs),
        "parallel": True,
    }


def _blocked(action: Action, db: Session, project: Project, by_stage: dict) -> str | None:
    api = _pipeline_api()
    pre = action.precondition
    if pre is None:
        return None
    if pre == "mom_confirmed":
        if by_stage[1].status == "confirmed":
            return None
        return api.blocked_reason(by_stage, 2) or "Confirm the MOM first (Stage 1)."
    if pre == "stage2_out":
        if by_stage[2].status in ISSUED:
            return None
        return api.blocked_reason(by_stage, 3)
    if pre == "stage3_out":
        if by_stage[3].status in ISSUED:
            return None
        return api.blocked_reason(by_stage, 4)
    if pre == "sow_exists":
        return None if _latest_sow(db, project) else "Draft the SOW revision first (sow.draft)."
    if pre == "procore_approved":
        if by_stage[4].status in api.PROCORE_APPROVED:
            return None
        # The reviewer's answer is recorded by hand on the Procore panel, and
        # that is the team's authoritative record: it unlocks the MTO as well.
        if (project.procore_status or "").strip().lower() in ("approved", "approved as noted"):
            return None
        return api.blocked_reason(by_stage, 5)
    if pre == "ear_exists":
        return None if project.ear is not None else "Draft the EAR first (ear.draft)."
    if pre == "ear_pi":
        ear = project.ear
        return None if (ear is not None and ear.status == "pi_signature") else (
            "Record the PI signature first (ear.pi_signature)."
        )
    return None


def allowed_actions(db: Session, project: Project) -> tuple[list[str], dict[str, str]]:
    """(allowed action ids, {action id: the reason it may not run})."""
    api = _pipeline_api()
    by_stage = api._rows(db, project.id)
    allowed: list[str] = []
    blocked: dict[str, str] = {}
    for action in ACTIONS.values():
        reason = _blocked(action, db, project, by_stage)
        if reason:
            blocked[action.id] = reason
        else:
            allowed.append(action.id)
    return allowed, blocked


def gate(db: Session, project: Project) -> dict:
    api = _pipeline_api()
    by_stage = api._rows(db, project.id)
    payload = api._payload(by_stage)
    stage = payload["current_stage"]
    allowed, blocked = allowed_actions(db, project)
    return {
        "stage": stage,
        "label": api.STAGES[stage],
        "status": by_stage[stage].status,
        "allowed": allowed,
        "blocked": blocked,
    }


def next_action(db: Session, project: Project) -> str | None:
    """The first action the delivery order would do next."""
    allowed, _blocked_map = allowed_actions(db, project)
    order = [
        "mom.draft", "mom.confirm",
        "summary.draft", "summary.approve",
        "ear.draft", "ear.pi_signature", "ear.asepc",
        "sow.draft", "boq.draft", "drawings.list", "sow.approve",
        "package.binder", "mto.draft",
    ]
    for action_id in order:
        if action_id in allowed:
            return action_id
    return None


def ai_status() -> dict:
    settings = get_settings()
    spec = provider.spec_for(settings)
    ok, reason = provider.available()
    return {
        "provider": spec.id if spec else "unknown",
        "model": provider.default_model_for(spec, settings) if spec else "",
        "available": bool(ok),
        "reason": reason,
    }


def provider_available() -> bool:
    ok, _reason = provider.available()
    return bool(ok)


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------
def record(db: Session, project: Project, role: str, content: str, *,
           actor_id: int | None = None, meta: dict | None = None) -> AssistantMessage:
    row = AssistantMessage(
        project_id=project.id, role=role, content=content or "", meta=meta, actor_id=actor_id
    )
    db.add(row)
    db.flush()
    return row


def turn(row: AssistantMessage) -> dict:
    meta = row.meta or {}
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content or "",
        "created_at": row.created_at or _now(),
        "action": meta.get("action"),
        "suggested_action": meta.get("suggested_action"),
        "needs_confirmation": bool(meta.get("needs_confirmation")),
        "artifacts": meta.get("artifacts") or [],
        "gate": meta.get("gate"),
        "elapsed_ms": meta.get("elapsed_ms"),
        "available": meta.get("available", True),
    }


def transcript(db: Session, project: Project, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.project_id == project.id)
        .order_by(AssistantMessage.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    # newest first from the database, oldest first in the transcript
    return [turn(row) for row in reversed(list(rows))]


def action_catalog() -> list[dict]:
    return [
        {
            "id": action.id,
            "label": action.label,
            "track": action.track,
            "stage": action.stage,
            "panel": action.panel,
            "capability": action.capability,
            "precondition": action.precondition,
        }
        for action in ACTIONS.values()
    ]


def capability_for(action_id: str) -> str | None:
    action = ACTIONS.get(action_id)
    return action.capability if action else None


# ---------------------------------------------------------------------------
# AI plumbing (monkeypatched in tests - no network in CI)
# ---------------------------------------------------------------------------
def _extract_json(raw: str | None) -> dict:
    """Pull the first JSON object out of a model reply (fences tolerated)."""
    if not raw:
        return {}
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _ai_json(system: str, prompt: str, *, model: str | None = None,
             provider_id: str | None = None) -> dict:
    """One chat completion, parsed as JSON. Returns {} when nothing usable comes back."""
    raw = provider.chat(
        [{"role": "user", "content": prompt}], system=system, model=model, provider=provider_id
    )
    return _extract_json(raw)


def _context(project: Project, db: Session, extra: str = "") -> str:
    payload = pipeline_state(db, project)
    stages = "\n".join(
        "  " + str(s["stage"]) + ". " + str(s["label"]) + ": " + str(s["status"])
        for s in payload["stages"]
    )
    ear = project.ear
    lines = [
        "PROJECT",
        "  PR: " + str(project.pr_number),
        "  Title: " + str(project.title),
        "  Location: " + str(project.location or "TBC"),
        "  PI / requester: " + str(project.pi_name or "TBC"),
        "  Workflow stage: " + str(project.stage),
        "FIVE-STAGE SPINE",
        stages,
        "EAR FUNNEL (parallel): " + str(ear.status if ear else "not started"),
        "DOCUMENTS",
        "  MOM: " + ("generated v" + str(project.mom.version) if project.mom else "none"),
        "  SOW revisions: " + str(len(project.sow_records)),
        "  Attachments: " + str(len(project.attachments)),
        "TRADE GROUPS (canonical, never reordered in the output)",
    ]
    lines += ["  " + code + " = " + name for code, name in trades_in_sow_order()]
    lines += [
        "RULES",
        "  Every trade: " + BASIS + ".",
        "  " + LABOUR_LINE,
        "  Materials, equipment and consumables only in any total.",
    ]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


_SYSTEM = (
    "You are the Project Delivery Assistant for the KAUST In-House Projects (IHP) team. "
    "You work inside their live app and you write documents the team signs. Be factual and "
    "terse: no pleasantries. Use the team's own vocabulary (PR, MOM, EAR, SOW, BOQ, MTO, "
    "Procore). Never invent prices, WBS numbers or approvals. Every trade is 'Supply & "
    "Install by IHP' and labour is in-house at $0.00."
)


def _propose_prompt(db: Session, project: Project, message: str, gate_info: dict) -> str:
    allowed = "\n".join(
        "  " + action_id + ": " + ACTIONS[action_id].label for action_id in gate_info["allowed"]
    )
    blocked = "\n".join(
        "  " + action_id + ": " + reason for action_id, reason in gate_info["blocked"].items()
    )
    parts = [
        _context(project, db),
        "THE TEAM JUST WROTE",
        message,
        "STEPS ALLOWED RIGHT NOW",
        allowed,
    ]
    if blocked:
        parts += ["STEPS NOT ALLOWED YET", blocked]
    parts.append(
        "Choose the ONE allowed step that this message is asking for. If the message is just "
        "information (notes, a scope description, a site update), choose the step that turns it "
        "into the next document."
    )
    parts.append(
        'Answer with JSON only: {"action": "<one allowed step id>", "reason": "<why, one '
        'sentence>", "reply": "<what you will do next, two sentences, addressed to the team>"}'
    )
    return "\n".join(parts)


def _action_prompt(db: Session, project: Project, action: Action, note: str | None) -> str:
    parts = [_context(project, db)]
    if note:
        parts += ["EXTRA INSTRUCTION FROM THE TEAM", note]
    parts += ["TASK", action.instruction, 'Answer with JSON only: {"data": { ... }}']
    return "\n".join(parts)


def _trade_data_instruction(kind: str) -> str:
    return (
        "Cover all six trade groups in this order: "
        + ", ".join(code + " " + name for code, name in trades_in_sow_order())
        + ". Every line is " + BASIS + ". Labour is $0.00: never add manpower cost. "
        + kind
    )


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The MOM's own words: template keys, and an agenda that is never empty
# ---------------------------------------------------------------------------
#: What the model tends to call things, mapped onto the template's keys.
_MOM_ALIASES = (
    ("date", "meeting_date"),
    ("location", "meeting_location"),
    ("time", "meeting_time"),
    ("title", "meeting_title"),
)

_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
_ACTION_HINT = re.compile(
    r"\b(action|actions|responsible|to be (?:issued|confirmed|submitted)|"
    r"\b(?:ihp|pi|hse|operations|fmom|ctps)\s+to\b|to issue|to confirm|to submit|"
    r"to finalise|to finalize|to provide)\b",
    re.I,
)
_ACTOR = re.compile(r"\b(IHP|PI|HSE|Building Operations|FMOM|CTPS|Proponent)\b", re.I)
_SCOPE_HINT = re.compile(
    r"\b(scope|agreed|works?|installation|install|replace|replacement|upgrade|"
    r"supply|provide|new |tie[- ]in|remove|relocat|repair|testing|commission)\b",
    re.I,
)
_SKIP_LINE = re.compile(r"^\s*(meeting|date|attendees?|invitation|organi[sz]er)\b", re.I)
_TRADE_HINT = (
    ("Civil / Architectural", ("civil", "architect", "trench", "concrete", "penetrat")),
    ("Electrical", ("electric", "panel", "cable", "earthing", "bonding", "power supply")),
    ("Low Current", ("low current", "low-current", "telecom", "bms", "detection", "scada",
                     "cctv", "tgm")),
    ("Plumbing", ("plumb", "gas", "pipe", "valve", "water", "drain")),
    ("HVAC", ("hvac", "duct", "ahu", "fcu", "ventilation", "chiller")),
    ("Fire Sprinkler", ("sprinkler", "fire-stop", "fire stop", "fire-rated")),
)


def _clean_agenda(value: Any) -> list[dict]:
    """Keep only the agenda rows that actually say something, in template shape."""
    rows: list[dict] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope") or item.get("description") or "").strip()
        if not scope:
            continue
        rows.append({
            "scope": scope,
            "trade": str(item.get("trade") or "").strip(),
            "action": str(item.get("action") or "").strip(),
            "responsible": str(item.get("responsible") or "").strip(),
            "etc": str(item.get("etc") or "").strip(),
        })
    return rows


def _agenda_from_notes(source_text: str | None) -> list[dict]:
    """One agenda row per scope point when the model returned none.

    Bullet or numbered lines win; otherwise sentences are used. A point that
    talks about an action keeps it, the actor becomes the responsible party and
    the trade is inferred so the MOM still sorts trade-wise.
    """
    text = (source_text or "").strip()
    if not text:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    bullets = [_BULLET.sub("", line).strip() for line in lines if _BULLET.match(line)]
    if bullets:
        # keep the bullet points, then whatever else was written around them
        # (the "Action:" line usually carries the responsible party)
        points = bullets + [line.strip() for line in lines if not _BULLET.match(line)]
    else:
        points = [p.strip() for p in re.split(r"(?<=[.!?])\s+", " ".join(lines)) if p.strip()]
    rows: list[dict] = []
    seen: set[str] = set()
    for point in points:
        if len(point) < 15 or _SKIP_LINE.match(point):
            continue
        if not (_SCOPE_HINT.search(point) or _ACTION_HINT.search(point)):
            continue
        key = point.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        actor = _ACTOR.search(point)
        lowered = point.lower()
        trade = next(
            (name for name, words in _TRADE_HINT if any(w in lowered for w in words)), ""
        )
        rows.append({
            "scope": point,
            "trade": trade,
            "action": point if _ACTION_HINT.search(point) else "",
            "responsible": actor.group(1) if actor else "",
            "etc": "",
        })
    return rows[:12]


def _mom_details(data: dict, source_text: str | None) -> tuple[dict, str]:
    """Normalise the model's MOM JSON: template keys and at least one agenda row.

    Returns (details, where the agenda came from) so the report can say whether
    the model, the notes or the request itself supplied it.
    """
    details = {k: v for k, v in (data or {}).items() if v not in (None, [], {})}
    for alias, key in _MOM_ALIASES:
        if not details.get(key) and details.get(alias):
            details[key] = details[alias]
    agenda = _clean_agenda(details.get("agenda"))
    source = "from the model" if agenda else ""
    if not agenda:
        agenda = _agenda_from_notes(source_text)
        source = "from your notes" if agenda else ""
    if agenda:
        details["agenda"] = agenda
    # With no agenda at all, build_mom_context supplies its own single row from
    # the project description, so the minute is never blank.
    return details, (source or "from the request")


def _source_text(db: Session, project: Project, note: str | None) -> str:
    """The team's own words for this run: the note, else the latest message."""
    if note and note.strip():
        return note.strip()
    row = db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.project_id == project.id, AssistantMessage.role == "user")
        .order_by(AssistantMessage.id.desc())
    ).first()
    return (row.content if row else "") or ""


def _mom_draft(db: Session, project: Project, user: User, data: dict, *,
               model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    mom_api = _mom_api()
    version = (project.mom.version + 1) if project.mom else 1
    details, agenda_source = _mom_details(data, source_text)
    if not details and project.mom and project.mom.details:
        details = dict(project.mom.details)
        agenda_source = "from the stored MOM"

    context = mom_api.build_mom_context(project, details, version)
    mom_dir = storage.project_dir(project.pr_number, "mom")
    docx_name = "MOM_" + storage.safe_name(project.pr_number) + "_v" + str(version) + ".docx"
    docx_path = docgen.render_docx(mom_api.MOM_TEMPLATE_NAME, context, mom_dir / docx_name)
    pdf_path = docgen.docx_to_pdf(docx_path)
    subject, body = emailer.build_mom_draft(project, context["items"], details=details, context=context)

    mom = project.mom
    if mom is None:
        mom = MomRecord(project_id=project.id, version=version, updated_by_id=user.id)
        db.add(mom)
    mom.version = version
    mom.status = "draft"
    mom.docx_filename = docx_name
    mom.pdf_filename = pdf_path.name if pdf_path else None
    mom.email_subject = subject
    mom.email_body = body
    mom.details = details
    mom.updated_by_id = user.id
    db.flush()

    agenda = context["agenda"]  # the built, trade-sorted agenda - never empty
    return {
        "summary": (
            "MOM v" + str(version) + " drafted from your notes: " + str(len(agenda))
            + " agenda item(s) (" + agenda_source + "), " + str(len(context["attendees"]))
            + " attendee(s). It is in the MOM panel, ready for you to confirm."
        ),
        "artifacts": [
            artifact("docx", "MOM v" + str(version), mom.docx_filename,
                     "/api/projects/" + str(project.id) + "/mom/download", "MomPanel",
                     {"version": version}),
            artifact("table", "MOM agenda", None, None, "MomPanel",
                     {"attendees": context["attendees"], "agenda": agenda[:15]}),
        ],
    }


def _summary_draft(db: Session, project: Project, user: User, data: dict, *,
                   model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    from . import summary_docgen

    data = data or {}
    trades = data.get("trades") or []
    rows = []
    total = 0.0
    for entry in trades:
        if not isinstance(entry, dict):
            continue
        amount = (float(entry.get("materials_sar") or 0.0)
                  + float(entry.get("equipment_sar") or 0.0)
                  + float(entry.get("consumables_sar") or 0.0))
        total += amount
        rows.append({
            "group": str(entry.get("group") or ""),
            "assessment": str(entry.get("assessment") or ""),
            "basis": BASIS,
            "materials_sar": round(amount, 2),
        })

    context = {
        "assessment": data.get("summary") or "",
        "scope": data.get("scope") or "",
        "trades": rows,
        "cost_estimate": {"total_sar": round(total, 2), "basis": BASIS, "labour": LABOUR_LINE},
    }
    path = summary_docgen.generate_project_summary_docx(project, context, db)
    return {
        "summary": (
            "Project assessment and cost estimate drafted (" + str(len(rows))
            + " trade line(s), total SAR " + format(round(total, 2), ",.2f")
            + " materials/equipment/consumables). " + LABOUR_LINE
        ),
        "artifacts": [
            artifact("docx", "Project Summary + Cost Estimate", Path(path).name,
                     "/api/projects/" + str(project.id) + "/generate/summary", "SowBoqPanel", {}),
            artifact("table", "Trade-wise cost estimate", None, None, "SowBoqPanel",
                     {"rows": rows, "total_sar": round(total, 2), "labour": LABOUR_LINE,
                      "basis": BASIS}),
        ],
    }


def _ear_draft(db: Session, project: Project, user: User, data: dict, *,
               model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    data = data or {}
    ear = project.ear
    if ear is None:
        ear = EarRecord(project_id=project.id, updated_by_id=user.id)
        db.add(ear)
        db.flush()

    ear.summary = str(data.get("summary") or ear.summary or "").strip()
    ear.recommendations = str(data.get("recommendations") or ear.recommendations or "").strip()
    budgets = data.get("trade_budgets") or {}
    if not isinstance(budgets, dict):
        budgets = {}
    ear.budget_data = {
        "trade_budgets": budgets,
        "billing_type": "pi_baseline",
        "basis": BASIS,
        "labour": LABOUR_LINE,
    }

    for row in list(ear.trade_inputs):
        db.delete(row)
    db.flush()
    created = 0
    for code, name in trades_in_sow_order():
        entry = budgets.get(code) or budgets.get(name) or {}
        if not isinstance(entry, dict):
            entry = {}
        db.add(EarTradeInput(
            ear_id=ear.id,
            trade=name,
            proposal=str(entry.get("proposal") or entry.get("assessment") or ""),
            estimated_materials_cost=float(entry.get("materials") or 0.0),
            # IHP is in-house: manpower never becomes a cost.
            estimated_manpower_cost=0.0,
            updated_by_id=user.id,
        ))
        created += 1
    ear.updated_by_id = user.id
    ear.updated_at = _now()
    db.flush()

    out_docx = (
        storage.project_dir(project.pr_number, "ear")
        / ("EAR_" + str(project.pr_number) + "_Rev" + str(ear.version).zfill(2) + ".docx")
    )
    docx_filename, pdf_filename = ear_docgen.generate_ear_document(project, ear, out_docx)
    ear.docx_filename = docx_filename
    ear.pdf_filename = pdf_filename
    db.flush()

    return {
        "summary": (
            "EAR v" + str(ear.version) + " drafted: " + str(created) + " trade input(s), manpower "
            "cost $0.00 (in-house). It is in the EAR panel; the funnel runs beside the five-stage spine."
        ),
        "artifacts": [
            artifact("record", "EAR v" + str(ear.version), docx_filename,
                     "/api/projects/" + str(project.id) + "/ear/download", "EarPanel",
                     {"status": ear.status}),
            artifact("table", "EAR trade budgets", None, None, "EarPanel",
                     {"budgets": budgets, "labour": LABOUR_LINE}),
        ],
    }


def _sow_draft(db: Session, project: Project, user: User, data: dict, *,
               model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    data = data or {}
    revision = "Rev-" + str(len(project.sow_records))

    supplied: dict[str, dict] = {}
    for entry in data.get("trade_sections") or []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("group") or entry.get("code") or "").strip().upper()[:1]
        match = next((c for c in SOW_ORDER if c == code), None)
        if match is None:
            g = generators.group_for_trade(str(entry.get("name") or entry.get("group") or ""))
            match = g[0] if g else None
        if match:
            supplied[match] = entry

    trades = []
    for code in SOW_ORDER:
        entry = supplied.get(code) or {}
        items = []
        for item in (entry.get("items") or entry.get("measurements") or []):
            if not isinstance(item, dict):
                continue
            items.append({
                "description": str(item.get("description") or ""),
                "sow_text": str(item.get("sow_text") or item.get("description") or ""),
                "unit": str(item.get("unit") or "Lot"),
                "qty": item.get("qty") or item.get("quantity") or "1",
                "source_tag": item.get("source_tag") or "DOC",
                "source_doc": item.get("source_doc") or "EAR",
            })
        mto_items = []
        for i, m in enumerate(entry.get("mto_items") or [], 1):
            if not isinstance(m, dict):
                continue
            mto_items.append({
                "ref": code + "." + str(i),
                "description": str(m.get("description") or ""),
                "unit": str(m.get("unit") or "Lot"),
                "qty": m.get("qty") or m.get("quantity") or "1",
                "computation": str(m.get("computation") or BASIS),
            })
        trades.append({
            "name": TRADE_NAMES.get(code, code),
            "seen": bool(items),
            "items": items,
            "mto_items": mto_items,
        })

    trade_sections = {
        "metadata": {"requester": project.pi_name or "TBC", "funding": BASIS},
        "drawings": [d for d in (data.get("drawings") or []) if isinstance(d, dict)],
        "trades": trades,
    }
    sow = SowRecord(
        project_id=project.id,
        revision_name=revision,
        status="draft",
        scope_text=str(data.get("scope_text") or ("Detailed Scope of Work for " + str(project.title))),
        trade_sections=trade_sections,
        created_by_id=user.id,
    )
    db.add(sow)
    db.flush()
    path = generators.generate_sow_docx(project, sow)
    seen = sum(1 for t in trades if t["items"])
    counts = [
        {"group": code, "name": TRADE_NAMES.get(code, code), "items": len(
            next((t for t in trades if t["name"] == TRADE_NAMES.get(code)), {}).get("items") or []
        )}
        for code in SOW_ORDER
    ]
    return {
        "summary": (
            "SOW " + revision + " created with " + str(seen) + " of 6 trade sections written; "
            "the Word document is in the SOW/BOQ panel."
        ),
        "artifacts": [
            artifact("docx", "SOW " + revision, Path(path).name,
                     "/api/projects/" + str(project.id) + "/generate/sow", "SowBoqPanel",
                     {"revision": revision}),
            artifact("table", "SOW trade sections", None, None, "SowBoqPanel", {"trades": counts}),
        ],
    }


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rows_from_sow(db: Session, project: Project) -> list[dict]:
    """Deterministic fallback: the SOW's own scope items become the BOQ/MTO lines.

    The model is the drafting help, not the source of truth - if its answer is
    unusable the BOQ must still come out with the SOW's measured lines.
    """
    sow = _latest_sow(db, project)
    if sow is None:
        return []
    rows: list[dict] = []
    for trade in ((sow.trade_sections or {}).get("trades") or []):
        if not isinstance(trade, dict):
            continue
        name = str(trade.get("name") or "")
        g = generators.group_for_trade(name)
        code = g[0] if g else "A"
        for i, item in enumerate(trade.get("items") or [], 1):
            if not isinstance(item, dict):
                continue
            rows.append({
                "trade": name or TRADE_NAMES.get(code, code),
                "item_code": code + "." + str(i),
                "description": str(item.get("description") or item.get("sow_text") or ""),
                "unit": str(item.get("unit") or "Lot"),
                "quantity": _as_float(item.get("qty") or item.get("quantity"), 1.0),
                "material_spec": str(item.get("material_spec") or ""),
            })
    return rows


def _boq_rows(data: dict) -> list[dict]:
    rows = []
    for entry in (data or {}).get("items") or []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("group") or entry.get("trade") or "").strip().upper()[:1]
        g = generators.group_for_trade(str(entry.get("trade") or entry.get("group") or ""))
        group = code if code in TRADE_NAMES else (g[0] if g else "A")
        rows.append({
            "trade": TRADE_NAMES.get(group, "Civil / Architectural"),
            "item_code": str(entry.get("item_code") or entry.get("code")
                             or (group + "." + str(len(rows) + 1))),
            "description": str(entry.get("description") or ""),
            "unit": str(entry.get("unit") or "Lot"),
            "quantity": _as_float(entry.get("quantity") or entry.get("qty"), 0.0),
            "material_spec": str(entry.get("material_spec") or ""),
        })
    return rows


def _write_items(db: Session, project: Project, rows: list[dict], mto_kind: str) -> list[BoqMtoItem]:
    items = []
    for row in rows:
        item = BoqMtoItem(
            project_id=project.id,
            mto_kind=mto_kind,
            trade=row["trade"],
            item_code=row["item_code"],
            description=row["description"],
            unit=row["unit"],
            quantity=row["quantity"],
            # IHP supplies and installs in-house: the BOQ goes out unpriced.
            unit_rate=0.0,
            total_rate=0.0,
            material_spec=row.get("material_spec") or None,
        )
        db.add(item)
        items.append(item)
    db.flush()
    return items


def _boq_draft(db: Session, project: Project, user: User, data: dict, *,
               model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    rows = _boq_rows(data)
    source = "from the assessment"
    if not rows:
        rows = _rows_from_sow(db, project)
        source = "from the SOW measurements"
    items = _write_items(db, project, rows, "design")
    sow = _latest_sow(db, project)
    path = generators.generate_boq_xlsx(project, items, sow)
    return {
        "summary": (
            "BOQ built with " + str(len(items)) + " line(s) " + source
            + " across the six trade groups, unpriced for bidding "
            "(unit rate 0.00, labour $0.00 in-house)."
        ),
        "artifacts": [
            artifact("xlsx", "Bill of Quantities", Path(path).name,
                     "/api/projects/" + str(project.id) + "/generate/boq", "SowBoqPanel",
                     {"items": len(items)}),
            artifact("table", "BOQ lines", None, None, "SowBoqPanel",
                     {"items": [{"trade": i.trade, "code": i.item_code, "description": i.description,
                                 "unit": i.unit, "qty": i.quantity} for i in items[:40]]}),
        ],
    }


def _drawings_list(db: Session, project: Project, user: User, data: dict, *,
                   model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    register: list[dict] = []
    for entry in (data or {}).get("drawings") or []:
        if isinstance(entry, dict):
            register.append({
                "drawing_no": str(entry.get("drawing_no") or entry.get("number") or "TBC"),
                "rev": str(entry.get("rev") or "0"),
                "title": str(entry.get("title") or ""),
                "discipline": str(entry.get("discipline") or ""),
                "date": str(entry.get("date") or ""),
                "status": str(entry.get("status") or "For Information"),
            })
    known = {d["drawing_no"].lower() for d in register}
    for att in project.attachments:
        name = (att.filename or "").lower()
        stem = name.rsplit(".", 1)[0]
        if name.endswith(".pdf") and stem not in known:
            register.append({
                "drawing_no": Path(att.filename).stem,
                "rev": str(att.version or 1),
                "title": att.filename,
                "discipline": "",
                "date": att.created_at.strftime("%Y-%m-%d") if att.created_at else "",
                "status": "As attached",
            })

    sow = _latest_sow(db, project)
    if sow is not None:
        sections = dict(sow.trade_sections or {})
        sections["drawings"] = register
        sow.trade_sections = sections
        db.flush()

    return {
        "summary": "Technical drawing list prepared: " + str(len(register))
                   + " drawing(s) registered on the SOW.",
        "artifacts": [
            artifact("table", "Technical drawing list", None, None, "SowBoqPanel", {"rows": register}),
        ],
    }


def _binder(db: Session, project: Project, user: User, data: dict, *,
            model: str | None = None, provider_id: str | None = None,
            source_text: str | None = None) -> dict:
    """Call the real binder (cover + SOW + BOQ + comment log + drawings)."""
    from ..api import sow_boq

    response = sow_boq.combined_binder(project.id, None, db, user)
    path = Path(getattr(response, "path", "") or "")
    pages = 0
    if path.exists():
        try:
            import pymupdf

            with pymupdf.open(path) as doc:
                pages = doc.page_count
        except Exception:  # noqa: BLE001 - the page count is informational
            pages = 0
    size = path.stat().st_size if path.exists() else 0
    return {
        "summary": "Procore binder built: " + str(pages) + " page(s), " + format(size, ",")
                   + " bytes - attached to the PR.",
        "artifacts": [
            artifact("pdf", "Procore Submittal Binder", path.name,
                     "/api/projects/" + str(project.id) + "/package/pdf", "ProcorePanel",
                     {"pages": pages, "bytes": size}),
        ],
    }


def _mto_draft(db: Session, project: Project, user: User, data: dict, *,
               model: str | None = None, provider_id: str | None = None,
               source_text: str | None = None) -> dict:
    rows = _boq_rows(data) or _rows_from_sow(db, project)
    items = _write_items(db, project, rows, "design")
    sow = _latest_sow(db, project)
    path = generators.generate_mto_xlsx(project, sow)
    return {
        "summary": (
            "Design MTO built with " + str(len(items)) + " line(s) - Procore has approved, so "
            "procurement can start from the MTO panel."
        ),
        "artifacts": [
            artifact("xlsx", "MTO Design", Path(path).name,
                     "/api/projects/" + str(project.id) + "/generate/mto", "MaterialPicker",
                     {"items": len(items)}),
        ],
    }


# ---------------------------------------------------------------------------
# Stage writers (the confirm / approve half of the conversation)
# ---------------------------------------------------------------------------
def _set_stage(db: Session, project: Project, stage: int, status: str) -> str:
    api = _pipeline_api()
    rows = api._rows(db, project.id)
    row = rows[stage]
    previous = row.status
    row.status = status
    db.flush()
    return "Stage " + str(stage) + " (" + api.STAGES[stage] + "): " + str(previous) + " to " + status + "."


def _stage_writer(db: Session, project: Project, user: User, action: Action,
                  note: str | None = None) -> dict:
    if action.id == "mom.confirm":
        message = _set_stage(db, project, 1, "confirmed")
        if (project.stage or "") == workflow.INTAKE:
            project.stage = workflow.MOM_CONFIRMED
        return {"summary": message + " The MOM is confirmed; the assessment and the EAR open now."}

    if action.id == "summary.approve":
        return {"summary": _set_stage(db, project, 2, "approved")
                + " The SOW package may be issued now."}

    if action.id == "sow.approve":
        return {"summary": _set_stage(db, project, 3, "approved")
                + " The Procore submittal may be compiled now."}

    if action.id == "ear.pi_signature":
        ear = project.ear
        ear.status = "pi_signature"
        ear.updated_by_id = user.id
        db.flush()
        return {"summary": "EAR funnel: Under PI signature."}

    if action.id == "ear.asepc":
        ear = project.ear
        ear.status = "asepc_pending"
        ear.updated_by_id = user.id
        db.flush()
        return {"summary": "EAR funnel: waiting for ASEPC approval (runs beside the spine)."}

    return {"summary": action.label}


# ---------------------------------------------------------------------------
# Register the actions
# ---------------------------------------------------------------------------
_register(Action(
    id="mom.draft", label="Draft the MOM from these notes", track="spine", stage=1,
    capability="mom.manage", panel="MomPanel", audit_key="assistant:mom", writer=_mom_draft,
    instruction=(
        "Turn the team's notes into the KAUST MOM fields. Use only what the notes say; leave a "
        "field out rather than inventing it.\n"
        '{"meeting_title": "...", "meeting_location": "...", "meeting_date": "YYYY-MM-DD", '
        '"meeting_time": "10:00-11:30", "meeting_number": "01", '
        '"attendees": [{"name": "...", "title": "...", "email": ""}], '
        '"agenda": [{"scope": "...", "trade": "...", "action": "...", "responsible": "...", '
        '"etc": "..."}]}\n'
        "Prose notes are normal: split them into ONE agenda row per scope point, and one row per "
        "trade where a trade is mentioned. Never return an empty agenda, and never leave the "
        "scope of a row empty."
    ),
))
_register(Action(
    id="mom.confirm", label="Confirm the MOM (stage 1)", track="spine", stage=1,
    capability="mom.manage", panel="PipelinePanel", audit_key="pipeline:stage",
))
_register(Action(
    id="summary.draft", label="Draft the assessment and cost estimate", track="spine", stage=2,
    capability="projects.edit", panel="SowBoqPanel", audit_key="assistant:summary",
    precondition="mom_confirmed", writer=_summary_draft,
    instruction=_trade_data_instruction(
        "Assess the scope and estimate cost per trade - materials, equipment and consumables only.\n"
        '{"summary": "...", "scope": "...", "trades": [{"group": "A", "assessment": "...", '
        '"materials_sar": 0, "equipment_sar": 0, "consumables_sar": 0}], "notes": "..."}'
    ),
))
_register(Action(
    id="summary.approve", label="Approve the assessment (stage 2)", track="spine", stage=2,
    capability="projects.edit", panel="PipelinePanel", audit_key="pipeline:stage",
    precondition="mom_confirmed",
))
_register(Action(
    id="ear.draft", label="Draft the EAR (runs beside the spine)", track="ear", stage=2,
    capability="ear.manage", panel="EarPanel", audit_key="assistant:ear",
    precondition="mom_confirmed", writer=_ear_draft,
    instruction=_trade_data_instruction(
        "Write the engineering assessment: findings, recommendations and a budget per trade. "
        "Manpower is always 0.\n"
        '{"summary": "...", "recommendations": "...", "trade_budgets": {"A": {"proposal": "...", '
        '"materials": 0}}}'
    ),
))
_register(Action(
    id="ear.pi_signature", label="Send the EAR for PI signature", track="ear", stage=2,
    capability="ear.manage", panel="EarPanel", audit_key="ear:funnel", precondition="ear_exists",
))
_register(Action(
    id="ear.asepc", label="Send the EAR to ASEPC approval", track="ear", stage=2,
    capability="ear.manage", panel="EarPanel", audit_key="ear:funnel", precondition="ear_pi",
))
_register(Action(
    id="sow.draft", label="Write the SOW trade sections", track="spine", stage=3,
    capability="sow.manage", panel="SowBoqPanel", audit_key="assistant:sow",
    precondition="stage2_out", writer=_sow_draft,
    instruction=_trade_data_instruction(
        "Write the scope of work and the measurement lines per trade.\n"
        '{"scope_text": "...", "trade_sections": [{"group": "A", "scope": "...", '
        '"items": [{"description": "...", "unit": "Lot", "qty": 1}], '
        '"mto_items": [{"description": "...", "unit": "Lot", "qty": 1, "computation": "..."}], '
        '"measurements": []}], "drawings": [{"drawing_no": "...", "rev": "0", "title": "...", '
        '"date": "..."}]}'
    ),
))
_register(Action(
    id="boq.draft", label="Build the BOQ from the SOW", track="spine", stage=3,
    capability="boq.manage", panel="SowBoqPanel", audit_key="assistant:boq",
    precondition="sow_exists", writer=_boq_draft,
    instruction=_trade_data_instruction(
        "Produce the bill of quantities lines from the SOW measurements. No rates: the BOQ is "
        "unpriced for bidding.\n"
        '{"items": [{"group": "A", "item_code": "A.1", "description": "...", "unit": "Lot", '
        '"quantity": 1}]}'
    ),
))
_register(Action(
    id="drawings.list", label="Prepare the technical drawing list", track="spine", stage=3,
    capability="sow.manage", panel="SowBoqPanel", audit_key="assistant:drawings",
    precondition="sow_exists", writer=_drawings_list,
    instruction=(
        "List every drawing this scope needs, whether or not it has been issued yet.\n"
        '{"drawings": [{"drawing_no": "...", "rev": "0", "title": "...", "discipline": "...", '
        '"date": "...", "status": "IFC"}]}'
    ),
))
_register(Action(
    id="sow.approve", label="Issue the SOW package (stage 3)", track="spine", stage=3,
    capability="sow.manage", panel="PipelinePanel", audit_key="pipeline:stage",
    precondition="sow_exists",
))
_register(Action(
    id="package.binder", label="Compile the Procore binder", track="spine", stage=4,
    capability="sow.manage", panel="ProcorePanel", audit_key="package:pdf",
    precondition="stage3_out", writer=_binder,
))
_register(Action(
    id="mto.draft", label="Build the design MTO (procurement)", track="spine", stage=5,
    capability="boq.manage", panel="MaterialPicker", audit_key="assistant:mto",
    precondition="procore_approved", writer=_mto_draft,
    instruction=_trade_data_instruction(
        "Produce the procurement take-off: what has to be bought and installed.\n"
        '{"items": [{"group": "A", "item_code": "A.1", "description": "...", "unit": "No.", '
        '"quantity": 1, "material_spec": "..."}]}'
    ),
))


# ---------------------------------------------------------------------------
# The two steps
# ---------------------------------------------------------------------------
def propose(db: Session, project: Project, user: User, message: str, *,
            model: str | None = None, provider_id: str | None = None) -> dict:
    """Record the team's message and propose one allowed action. Writes nothing else."""
    started = time.time()
    text = (message or "").strip()
    if not text:
        raise ValueError("The message is empty.")
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS]

    record(db, project, "user", text, actor_id=user.id)
    db.commit()

    gate_info = gate(db, project)
    allowed = gate_info["allowed"]
    if not allowed:
        row = record(db, project, "assistant",
                     "Every step is already done on this project; nothing left to run.",
                     actor_id=user.id, meta={"gate": gate_info})
        db.commit()
        return turn(row)

    data = _ai_json(
        _SYSTEM + " You are choosing the next step.",
        _propose_prompt(db, project, text, gate_info),
        model=model, provider_id=provider_id,
    )
    candidate = str((data or {}).get("action") or "").strip()
    action_id = candidate if candidate in allowed else (next_action(db, project) or allowed[0])
    reason = str((data or {}).get("reason") or "").strip() or "The next allowed step on this project."
    reply = str((data or {}).get("reply") or "").strip() or ("Next step: " + ACTIONS[action_id].label + ".")

    elapsed = int((time.time() - started) * 1000)
    row = record(db, project, "assistant", reply, actor_id=user.id, meta={
        "suggested_action": action_id,
        "needs_confirmation": True,
        "reason": reason,
        "elapsed_ms": elapsed,
        "gate": gate_info,
        "available": provider_available(),
    })
    db.commit()
    out = turn(row)
    out["gate"] = gate_info
    return out


def run_action(db: Session, project: Project, user: User, action_id: str, *,
               note: str | None = None, model: str | None = None,
               provider_id: str | None = None) -> dict:
    """Execute one action, or raise GateBlocked when the pipeline says no."""
    started = time.time()
    action = ACTIONS.get(action_id)
    if action is None:
        raise KeyError(action_id)

    _allowed, blocked = allowed_actions(db, project)
    if action_id in blocked:
        raise GateBlocked(blocked[action_id])

    data: dict = {}
    if action.writer is not None:
        plan = _ai_json(
            _SYSTEM, _action_prompt(db, project, action, note),
            model=model, provider_id=provider_id,
        )
        candidate = (plan or {}).get("data")
        if isinstance(candidate, dict):
            data = candidate

    source_text = _source_text(db, project, note)
    if action.writer is not None:
        result = action.writer(db, project, user, data, model=model, provider_id=provider_id,
                               source_text=source_text)
    else:
        result = _stage_writer(db, project, user, action, note=note)

    summary = str(result.get("summary") or action.label)
    if note:
        summary += " Note recorded: " + note.strip()
    elapsed = int((time.time() - started) * 1000)
    if elapsed > SOFT_BUDGET_S * 1000:
        summary += " (took " + str(round(elapsed / 1000)) + "s)"

    workflow.log_action(
        db, user, action.audit_key, project,
        {"action": action.id, "panel": action.panel, "elapsed_ms": elapsed,
         "note": (note or None),
         "artifacts": [a.get("filename") for a in result.get("artifacts") or []]},
    )
    gate_info = gate(db, project)
    row = record(db, project, "tool", summary, actor_id=user.id, meta={
        "action": action.id,
        "artifacts": result.get("artifacts") or [],
        "elapsed_ms": elapsed,
        "gate": gate_info,
    })
    db.commit()
    out = turn(row)
    out["gate"] = gate_info
    out["action"] = action.id
    return out
