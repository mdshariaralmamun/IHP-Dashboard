"""AI chat, ask, and corpus endpoints.

Routes:
  POST /api/ai/chat          – project-scoped chat
  POST /api/ai/ask           – Q&A (returns AiAnswer schema)
  GET  /api/ai/corpus        – list knowledge-base documents
  POST /api/ai/corpus/upload – upload a document to the knowledge base
  DELETE /api/ai/corpus/{id} – remove a document from the knowledge base
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai import facts as facts_mod
from ..ai import provider, retrieval
from ..ai.corpus import chunk_text
from ..core.config import get_settings
from ..core.rbac import CAP_USERS_MANAGE, get_current_user, require_capability
from ..db import get_db
from ..models import (
    BoqMtoItem,
    CloseoutRecord,
    ConstructionMtoItem,
    ConstructionRecord,
    CorpusChunk,
    CorpusDocument,
    EarRecord,
    IcrHandoff,
    MomRecord,
    Project,
    SowRecord,
    User,
)

router = APIRouter(prefix="/ai", tags=["ai"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ChatIn(BaseModel):
    project_id: int | None = None
    message: str
    scope: str = "all"  # "all" | "project" | "standards"
    #: Optional per-request model override (Ollama model name or vendor model).
    model: str | None = None
    #: Optional per-request provider override (see GET /api/ai/providers).
    provider: str | None = None


class ChatOut(BaseModel):
    reply: str
    citations: list[dict] = []
    available: bool


class AskIn(BaseModel):
    question: str
    project_id: int | None = None
    #: Optional per-request model override (Ollama model name or vendor model).
    model: str | None = None
    #: Optional per-request provider override (see GET /api/ai/providers).
    provider: str | None = None
    #: Previous turns, oldest first: [{"role": "user"|"assistant", "content": ...}].
    #: Lets "and which of those are overdue?" resolve against the last answer.
    history: list[dict[str, str]] | None = None


class AskOut(BaseModel):
    answer: str
    mode: str  # "llm" (model answer) | "live" (exact database answer) | "extractive"
    sources: list[dict] = []


class FeedbackIn(BaseModel):
    question: str
    answer: str = ""
    rating: str  # "up" | "down"
    mode: str = "llm"
    model: str | None = None
    project_id: int | None = None
    comment: str | None = None
    sources: list[dict] = []


class CorpusDocOut(BaseModel):
    id: int
    filename: str
    source: str
    project_id: int | None
    chunk_count: int
    created_at: str

    model_config = {"from_attributes": True}


class CorpusUploadOut(BaseModel):
    id: int
    filename: str
    chunk_count: int
    embedded: bool


# ---------------------------------------------------------------------------
# Database context builder
# ---------------------------------------------------------------------------

STAGE_LABELS = {
    "INTAKE": "Intake / Scoping",
    "MOM_CONFIRMED": "MOM Confirmed",
    "EAR_REVIEW": "EAR Review",
    "DISPOSITION": "Disposition",
    "SOW_BOQ": "SOW / BOQ",
    "ICR": "ICR / Approval",
    "CONSTRUCTION": "Construction",
    "CLOSEOUT": "Closeout & Handover",
    "PUNCH_LIST": "Punch List",
}


def _derive(project: Project) -> dict:
    """Planner-derived fields (division, dates, completion, flags)."""
    from .projects import _derive_tracker_fields

    return _derive_tracker_fields(project)


def _fmt_project(p: Project, derived: dict | None = None) -> str:
    derived = derived if derived is not None else _derive(p)
    stage = STAGE_LABELS.get(p.stage or "", p.stage or "Unknown")
    division = derived.get("phase") or "Unassigned"
    lines = [
        f"Project: {p.pr_number} — {p.title}",
        f"  Division: {division} | Stage: {stage} | Priority: {derived.get('priority') or 'N/A'}",
        f"  Location: {p.location or 'N/A'}",
        f"  PI: {p.pi_name or 'N/A'} ({p.pi_email or 'N/A'})",
        f"  Funding: {p.funding_source or 'N/A'}",
        f"  Disposition: {p.disposition or 'N/A'}",
        f"  Created: {p.created_at.strftime('%Y-%m-%d') if p.created_at else 'N/A'}",
    ]
    # Planner schedule: what "on time" actually means for this project.
    schedule = []
    if derived.get("start_date"):
        schedule.append(f"start {derived['start_date']}")
    if derived.get("finish_date"):
        schedule.append(f"finish {derived['finish_date']}")
    if derived.get("completion_pct") is not None:
        schedule.append(f"{derived['completion_pct']}% complete")
    if derived.get("effort"):
        schedule.append(f"effort {derived['effort']}")
    if derived.get("duration"):
        schedule.append(f"duration {derived['duration']}")
    if schedule:
        lines.append("  Planner schedule: " + ", ".join(schedule))
    if derived.get("planner_sync_date"):
        lines.append(f"  Planner sync: {derived['planner_sync_date']}")
    status = []
    if derived.get("latest_status"):
        status.append(f"latest status {derived['latest_status']}")
    if derived.get("latest_status_date"):
        status.append(f"as of {derived['latest_status_date']}")
    if derived.get("checklist"):
        status.append(f"checklist {derived['checklist']}")
    if derived.get("flags"):
        status.append("flags " + ", ".join(derived["flags"]))
    if status:
        lines.append("  Tracker: " + " | ".join(status))
    if derived.get("ear_substatus"):
        ear = f"  EAR status: {derived['ear_substatus']}"
        if derived.get("ear_approved_date"):
            ear += f" (approved {derived['ear_approved_date']})"
        lines.append(ear)
    if derived.get("trades"):
        lines.append("  Trades: " + ", ".join(derived["trades"]))
    # People: who the Planner assigned the task to, plus the execution lead
    # and the requestor/PI column. "Assigned To" is what "EAR assigned to"
    # means in the tracker.
    people = []
    if derived.get("assigned_to"):
        people.append(f"assigned to {derived['assigned_to']}")
    if derived.get("execution_lead"):
        people.append(f"execution lead {derived['execution_lead']}")
    if derived.get("requestor"):
        people.append(f"requestor/PI {derived['requestor']}")
    if people:
        lines.append("  People: " + " | ".join(people))
    return "\n".join(lines)


def _extract_pr_numbers(text: str) -> list[str]:
    """Extract PR numbers from a query, e.g. PR=11699, PR-11699, PR#11699, #11699."""
    patterns = [
        r"PR[=\-#\s]+(\d+)",
        r"#(\d{4,6})",
        r"\bpr[=\-#\s]+(\d+)",
    ]
    found = []
    for pat in patterns:
        found.extend(re.findall(pat, text, re.IGNORECASE))
    return list(set(found))


#: "this / it / the project" -> the question is about the scoped project,
#: so portfolio-wide counting answers must not be used.
_DEICTIC = re.compile(
    r"\b(this|these|it|its|the project|current project|this one|here)\b", re.I
)

#: A portfolio-wide question must never be answered with one project's record.
_PORTFOLIO = re.compile(
    r"\b(projects|portfolio|overall|across|everything|all prs?)\b", re.I
)


def _history_messages(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Turn the client's transcript into chat turns (last 6, trimmed)."""
    turns: list[dict[str, str]] = []
    for turn in (history or [])[-4:]:
        role = str(turn.get("role", "")).lower()
        content = str(turn.get("content") or turn.get("text") or "").strip()
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": content[:400]})
    return turns


def _build_project_context(
    question: str, project_id: int | None, db: Session, facts: dict | None = None
) -> tuple[str, list[dict]]:
    """Build the context handed to the model.

    A question naming a project gets that project's live record (plus its
    MOM / EAR / SOW / material / construction detail). Anything else gets the
    authoritative live fact pack from app.ai.facts. Returns
    (context_text, sources_list).
    """
    context_parts: list[str] = []
    sources: list[dict] = []

    # 1. Check for explicit PR numbers in the question
    pr_numbers = _extract_pr_numbers(question)
    matched_projects: list[Project] = []

    for pr_num in pr_numbers:
        # Try exact match: PR-XXXXX or PR=XXXXX
        candidates = db.query(Project).filter(
            Project.pr_number.ilike(f"%{pr_num}%")
        ).all()
        matched_projects.extend(candidates)

    # 2. If a project_id is scoped, load that project
    if project_id is not None:
        scoped = db.get(Project, project_id)
        if scoped and scoped not in matched_projects:
            matched_projects.insert(0, scoped)

    # 3. Build context for each matched project
    for proj in matched_projects:
        proj_text = _fmt_project(proj)
        context_parts.append(proj_text)  # includes division, schedule, tracker state
        sources.append({"filename": f"Project {proj.pr_number}", "snippet": f"{proj.title} — Stage: {STAGE_LABELS.get(proj.stage or '', proj.stage or 'Unknown')}"})

        # MOM records
        moms = db.query(MomRecord).filter(MomRecord.project_id == proj.id).order_by(MomRecord.created_at.desc()).limit(3).all()
        for mom in moms:
            details = mom.details or {}
            attendees = ", ".join(details.get("attendees", [])) if isinstance(details.get("attendees"), list) else str(details.get("attendees", ""))
            agenda_raw = details.get("agenda_items", [])
            agenda_text = ""
            if isinstance(agenda_raw, list):
                agenda_text = "; ".join(
                    (item.get("topic", "") if isinstance(item, dict) else str(item))
                    for item in agenda_raw[:5]
                )
            mom_line = f"  MOM v{mom.version} [{mom.status}]: attendees={attendees or 'N/A'}"
            if agenda_text:
                mom_line += f", agenda: {agenda_text}"
            context_parts.append(mom_line)
            sources.append({"filename": f"MOM v{mom.version} ({proj.pr_number})", "snippet": mom_line})

        # EAR records
        ears = db.query(EarRecord).filter(EarRecord.project_id == proj.id).order_by(EarRecord.created_at.desc()).limit(2).all()
        for ear in ears:
            ear_line = f"  EAR v{ear.version} [{ear.status}]: {(ear.summary or '')[:200]}"
            context_parts.append(ear_line)
            sources.append({"filename": f"EAR v{ear.version} ({proj.pr_number})", "snippet": ear_line})

        # SOW
        sows = db.query(SowRecord).filter(SowRecord.project_id == proj.id).order_by(SowRecord.created_at.desc()).limit(1).all()
        for sow in sows:
            sow_line = f"  SOW [{sow.status}] rev={sow.revision_name}: {(sow.scope_text or '')[:300]}"
            context_parts.append(sow_line)
            sources.append({"filename": f"SOW ({proj.pr_number})", "snippet": sow_line})

        # Material tracking (via construction MTO items)
        mats = db.query(ConstructionMtoItem).filter(ConstructionMtoItem.project_id == proj.id).all()
        if mats:
            mat_summary = f"  Material tracking: {len(mats)} items"
            statuses = {}
            for m in mats:
                statuses[m.delivery_status] = statuses.get(m.delivery_status, 0) + 1
            mat_summary += " | " + ", ".join(f"{k}: {v}" for k, v in statuses.items())
            context_parts.append(mat_summary)
            sources.append({"filename": f"Materials ({proj.pr_number})", "snippet": mat_summary})

        # Work permits (stored in ConstructionRecord.wcf_data JSON)
        cons = db.query(ConstructionRecord).filter(ConstructionRecord.project_id == proj.id).first()
        if cons:
            con_line = f"  Construction: status={cons.status}"
            if cons.wcf_data:
                con_line += f", work-permit/WCF data available"
            context_parts.append(con_line)

        # ICR handoffs
        icrs = db.query(IcrHandoff).filter(IcrHandoff.project_id == proj.id).all()
        if icrs:
            icr_summary = "  ICR handoffs: " + ", ".join(f"{getattr(i, 'milestone', '')}={getattr(i, 'status', '')}" for i in icrs)
            context_parts.append(icr_summary)

        # Closeout
        closeout = db.query(CloseoutRecord).filter(CloseoutRecord.project_id == proj.id).first()
        if closeout:
            final_cost = getattr(closeout, 'final_cost_sar', getattr(closeout, 'final_cost', 'N/A'))
            handover = getattr(closeout, 'handover_date', getattr(closeout, 'client_signoff_date', 'N/A'))
            co_line = f"  Closeout: status={closeout.status}, final_cost={final_cost}, handover={handover}"
            context_parts.append(co_line)

    # 4. No specific project was named: hand the model the authoritative live
    #    fact pack (totals, divisions, stages, overdue / due / on-hold lists).
    #    The old keyword search over titles/descriptions matched generic words
    #    such as "total" or "project" and answered with unrelated projects, so
    #    it is gone; the fact pack always carries the real numbers.
    if not matched_projects:
        pack = facts if facts is not None else facts_mod.collect(db)
        context_parts.append(facts_mod.render(pack))
        sources = facts_mod.sources(pack) + sources

    return "\n".join(context_parts), sources


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the KAUST IHP (In-House Projects) assistant.

The context you receive contains one or more of these blocks:
- [Live IHP database - authoritative]: current facts read from the platform
  database. The "QUICK ANSWERS" lines are exact values.
- A single project record (when the question names a PR number, or when the
  user is asking from that project's page), including division, stage, Planner
  schedule, tracker state, MOM / EAR / SOW / material records.
- [Knowledge base documents]: older reference documents.

Rules:
1. For any number, count, date, stage, division or list of projects use ONLY the
   live fact pack. Copy the QUICK ANSWERS values exactly - never recompute them.
2. Never invent a project, PR number, date, percentage or count. If the context
   does not contain the answer, reply "I don't have that in the live data." and
   name the missing field in one short sentence.
3. If a list in the facts is empty (for example "Overdue: 0"), answer "None" -
   never substitute examples from another list.
4. Do not repeat a project list from an earlier turn unless it still answers the
   current question.
5. Keep answers short and structured: one direct answer line first, then at most
   5 bullets. Use **bold** for key numbers and PR numbers. No preamble and do
   not restate the question.
6. When asked to draft, summarise or explain you may write prose, but every fact
   in it must come from the context.
7. The reference-document excerpts come from the IHP engineering archive and from
   documents uploaded to the dashboard. Prefer them for "how did we do this
   before?", specifications, quantities and past wording, and name the file you
   used. They may be older than the live facts.

Stage progression: Intake -> MOM Confirmed -> EAR Review -> Disposition ->
SOW/BOQ -> ICR -> Construction -> Closeout -> Punch List.
Divisions: EAR, Design, Construction, Close-up.
"""


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.get("/models")
def ai_models(
    provider_id: str | None = None,
    _user: User = Depends(get_current_user),
):
    """Models the assistant can use, for the chat model switcher.

    Ollama returns the pulled local models; cloud vendors are asked for their
    catalogue when a key is configured, otherwise the catalogue's suggestions
    come back flagged `source: "suggested"`.
    """
    from ..ai import providers_catalog

    settings = get_settings()
    effective = provider_id or provider.effective_provider(settings)
    spec = providers_catalog.resolve(effective)
    model = provider.default_model_for(spec, settings) if spec else ""
    return {
        "provider": effective,
        "provider_label": spec.label if spec else effective,
        "active": model,
        "models": provider.list_models(provider_id),
    }


@router.get("/providers")
def ai_providers(_user: User = Depends(get_current_user)):
    """The provider catalogue: every market API the platform can talk to.

    A provider is `configured` when a key (or, for local servers, a reachable
    base URL) is present. The Settings page renders this list.
    """
    from ..ai import providers_catalog
    from ..services import runtime_settings

    settings = get_settings()
    overrides = runtime_settings.read_overrides()
    selected = provider.effective_provider(settings)

    out = []
    for spec in providers_catalog.all_specs():
        key = provider.api_key_for(spec, settings)
        configured = bool(key) or spec.kind == "ollama" or spec.id == "custom"
        out.append({
            "id": spec.id,
            "label": spec.label,
            "kind": spec.kind,
            "local": spec.local,
            "docs": spec.docs,
            "notes": spec.notes,
            "default_models": list(spec.default_models),
            "base_url": provider.base_url_for(spec, settings),
            "model": provider.default_model_for(spec, settings),
            "key_env": spec.env_key,
            "key_present": bool(key),
            "configured": configured,
            "selected": spec.id == selected,
            "has_saved_key": bool(overrides.get(f"AI_KEY_{spec.id.upper()}")),
        })
    return {"selected": selected, "count": len(out), "providers": out}


class ProviderTestIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


@router.post("/providers/test")
def ai_provider_test(
    body: ProviderTestIn,
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Send a one-token prompt to a provider and report what happened.

    Lets an admin verify a key/base URL before switching the whole platform
    over to it. Credentials in the body are used for this probe only and are
    never stored here (save them through the Settings endpoint).
    """
    import time as _time

    from ..ai import providers_catalog
    from ..services import runtime_settings

    settings = get_settings()
    spec = providers_catalog.resolve(body.provider or provider.effective_provider(settings))
    if spec is None:
        raise HTTPException(400, f"Unknown provider {body.provider!r}")

    saved = runtime_settings.read_overrides()
    try:
        if body.base_url:
            runtime_settings.write_overrides(
                {**saved, f"AI_BASE_URL_{spec.id.upper()}": body.base_url.strip()}
            )
        if body.api_key:
            runtime_settings.write_overrides(
                {**saved, f"AI_KEY_{spec.id.upper()}": body.api_key.strip()}
            )
        started = _time.time()
        reply = provider.chat(
            [{"role": "user", "content": "Reply with the single word: ready"}],
            model=body.model,
            provider=spec.id,
        )
        elapsed = round(_time.time() - started, 2)
    finally:
        runtime_settings.write_overrides(saved)

    if reply is None:
        return {
            "ok": False, "provider": spec.id, "label": spec.label,
            "seconds": elapsed,
            "error": "No response - check the API key, the base URL and the model name.",
        }
    return {
        "ok": True, "provider": spec.id, "label": spec.label,
        "model": body.model or provider.default_model_for(spec, settings),
        "seconds": elapsed, "reply": reply.strip()[:200],
    }


@router.post("/chat", response_model=ChatOut)
def chat(
    body: ChatIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Project-scoped Q&A over the corpus + memory."""
    # Counts and lists are answered straight from the database, so a small local
    # model cannot get them wrong - and they still work with no AI provider at
    # all. Open-ended questions go to the model below with the full context.
    facts = facts_mod.collect(db)
    pr_numbers = _extract_pr_numbers(body.message)
    if body.project_id is not None and not _PORTFOLIO.search(body.message):
        target = db.get(Project, body.project_id)
        if target is not None:
            direct = facts_mod.project_answer(
                body.message, target, _derive(target)
            )
            if direct:
                return ChatOut(
                    reply=direct,
                    citations=[facts_mod.project_source(target, _derive(target))],
                    available=True,
                )
    if not pr_numbers and not (
        body.project_id is not None and _DEICTIC.search(body.message)
    ):
        direct = facts_mod.answer(body.message, facts)
        if direct:
            return ChatOut(
                reply=direct, citations=facts_mod.sources(facts), available=True
            )

    is_available, reason = provider.available()
    if not is_available:
        return ChatOut(
            reply=(
                "The AI provider is currently offline. "
                "Configure AI_PROVIDER and the matching API key in .env to enable it."
                + (f" (reason: {reason})" if reason else "")
            ),
            citations=[],
            available=False,
        )

    db_context, sources = _build_project_context(
        body.message, body.project_id, db, facts=facts
    )
    hits = retrieval.search(body.message, db, k=5)
    citations = [{"filename": h["filename"], "snippet": h["text"][:200]} for h in hits]

    user_content = body.message
    if db_context:
        user_content = f"Database context:\n{db_context}\n\nQuestion: {body.message}"

    reply = provider.chat(
        [{"role": "user", "content": user_content}],
        system=SYSTEM_PROMPT,
        model=body.model,
        provider=body.provider,
    )
    text = reply or "(no response from provider)"
    unknown = facts_mod.unknown_pr_numbers(text, facts["pr_numbers"])
    if unknown:
        text += (
            "\n\n_Note: " + ", ".join(unknown)
            + " is not in the live database - treat that as unverified._"
        )
    return ChatOut(reply=text, citations=citations + sources[:3], available=True)


# ---------------------------------------------------------------------------
# Ask endpoint (used by AiChat.tsx)
# ---------------------------------------------------------------------------


@router.post("/ask", response_model=AskOut)
def ask(
    body: AskIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Project-scoped Q&A returning the AiAnswer schema the frontend expects."""
    # One database pass: the live fact pack feeds both the deterministic
    # answers below and the model context.
    facts = facts_mod.collect(db)

    # Deterministic fast path. Nothing below invents data: "which projects are
    # overdue?", "how many construction projects", "total projects", "ICR
    # count" are answered from the database itself, and they work even when no
    # AI provider is configured.
    pr_numbers = _extract_pr_numbers(body.question)
    portfolio_question = bool(_PORTFOLIO.search(body.question))

    # Single-project questions (asked from a project page, or naming a PR
    # number) get the record: finish date, progress, risks, tracker status.
    target: Project | None = (
        db.get(Project, body.project_id) if body.project_id is not None else None
    )
    if target is None and len(pr_numbers) == 1:
        target = (
            db.query(Project)
            .filter(Project.pr_number.ilike(f"%{pr_numbers[0]}%"))
            .first()
        )
    if target is not None and not portfolio_question:
        derived = _derive(target)
        direct = facts_mod.project_answer(body.question, target, derived)
        if direct:
            return AskOut(
                answer=direct,
                mode="live",
                sources=[facts_mod.project_source(target, derived)],
            )

    if not pr_numbers and not (
        body.project_id is not None and _DEICTIC.search(body.question)
    ):
        direct = facts_mod.answer(body.question, facts)
        if direct:
            return AskOut(
                answer=direct, mode="live", sources=facts_mod.sources(facts)
            )

    is_available, reason = provider.available()
    if not is_available:
        return AskOut(
            answer=(
                "I can answer counts and lists from the live database, but the "
                "language model is offline so open questions are unavailable. "
                "Configure AI_PROVIDER and its API key in .env to enable it."
                + (f" (reason: {reason})" if reason else "")
            ),
            mode="extractive",
            sources=facts_mod.sources(facts),
        )

    db_context, db_sources = _build_project_context(
        body.question, body.project_id, db, facts=facts
    )

    # Document retrieval: the engineering archive + documents uploaded to the
    # dashboard, scoped to the project when the question is about one.
    # Excerpts are kept short: the Cloudflare proxy aborts a response after
    # ~100 s, and on this CPU-only host every extra 1,000 prompt characters of
    # prefill is several seconds of latency.
    hits = retrieval.search(
        body.question, db, k=4, project_id=body.project_id, max_chars=800
    )
    corpus_sources = [
        {"filename": h["filename"], "snippet": h["text"][:200]} for h in hits
    ]

    # Build user message with all context
    user_content = body.question
    context_blocks = []
    if db_context:
        context_blocks.append(db_context)
    if hits:
        corpus_text = "\n\n".join(
            f"[{h['filename']} | chunk {h['chunk_index']}]\n{h['text']}" for h in hits
        )
        context_blocks.append(
            "[Reference documents - the IHP engineering archive and documents "
            "uploaded to the dashboard, retrieved by relevance]\n"
            "These excerpts are real project documents. When you use one, mention "
            "its file name. Where a document disagrees with the live database "
            "facts above, the live facts win.\n\n" + corpus_text
        )

    if context_blocks:
        user_content = "\n\n".join(context_blocks) + f"\n\nQuestion: {body.question}"

    messages = _history_messages(body.history) + [
        {"role": "user", "content": user_content}
    ]
    reply = provider.chat(
        messages, system=SYSTEM_PROMPT, model=body.model, provider=body.provider
    )
    text = reply or "(no response from provider)"

    # Hallucination guard: a PR number that is not in the database is flagged
    # instead of being presented as fact.
    unknown = facts_mod.unknown_pr_numbers(text, facts["pr_numbers"])
    if unknown:
        text += (
            "\n\n_Note: " + ", ".join(unknown)
            + " is not in the live database - treat that as unverified._"
        )

    all_sources = db_sources + corpus_sources
    return AskOut(answer=text, mode="llm", sources=all_sources[:6])


# ---------------------------------------------------------------------------
# Retrieval, feedback and training data
# ---------------------------------------------------------------------------


@router.get("/search")
def ai_search(
    q: str,
    k: int = 5,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Document retrieval only (no model) - used to verify the corpus."""
    from ..ai import retrieval

    hits = retrieval.search(q, db, k=max(1, min(k, 20)), project_id=project_id)
    return {
        "query": q,
        "count": len(hits),
        "corpus": retrieval.stats(db),
        "hits": [
            {
                "filename": hit["filename"],
                "chunk_index": hit["chunk_index"],
                "score": hit["score"],
                "keyword_score": hit["keyword_score"],
                "vector_score": hit["vector_score"],
                "snippet": hit["text"][:400],
            }
            for hit in hits
        ],
    }


@router.post("/feedback")
def ai_feedback(
    body: FeedbackIn,
    user: User = Depends(get_current_user),
):
    """Record a 👍/👎 on an answer; this is the local training signal."""
    from ..services import ai_training

    if body.rating not in ("up", "down"):
        raise HTTPException(400, "rating must be 'up' or 'down'")
    return ai_training.record_feedback(user.id, body.model_dump())


@router.get("/feedback/stats")
def ai_feedback_stats(
    _admin: User = Depends(get_current_user),
):
    from ..services import ai_training

    return ai_training.feedback_stats()


@router.post("/training/export")
def ai_training_export(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Export the chat-format fine-tuning dataset (feedback + live fact pairs)."""
    from ..services import ai_training

    return ai_training.export_dataset(db)


# ---------------------------------------------------------------------------
# Corpus (knowledge base) endpoints
# ---------------------------------------------------------------------------


@router.get("/corpus", response_model=list[CorpusDocOut])
def list_corpus(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List all documents in the knowledge base."""
    docs = db.query(CorpusDocument).order_by(CorpusDocument.created_at.desc()).all()
    return [
        CorpusDocOut(
            id=doc.id,
            filename=doc.filename,
            source=doc.source,
            project_id=doc.project_id,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at.isoformat(),
        )
        for doc in docs
    ]


@router.post("/corpus/upload", response_model=CorpusUploadOut)
async def upload_corpus_doc(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a document to the knowledge base and chunk it."""
    filename = file.filename or "unknown"
    content_bytes = await file.read()

    try:
        text = content_bytes.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read file as text.")

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="File appears to be empty or unreadable.")

    doc = CorpusDocument(
        filename=filename,
        source="upload",
        chunk_count=len(chunks),
        uploaded_by_id=current_user.id,
    )
    db.add(doc)
    db.flush()

    for idx, chunk_text_val in enumerate(chunks):
        db.add(CorpusChunk(
            document_id=doc.id,
            chunk_index=idx,
            text=chunk_text_val,
            project_id=None,
        ))

    db.commit()
    db.refresh(doc)

    return CorpusUploadOut(
        id=doc.id,
        filename=doc.filename,
        chunk_count=doc.chunk_count,
        embedded=False,
    )


@router.delete("/corpus/{doc_id}", status_code=204)
def delete_corpus_doc(
    doc_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Remove a document and all its chunks from the knowledge base."""
    doc = db.get(CorpusDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    db.query(CorpusChunk).filter(CorpusChunk.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()
