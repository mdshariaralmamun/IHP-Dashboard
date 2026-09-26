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

from ..ai import provider, retrieval
from ..ai.corpus import chunk_text
from ..core.rbac import get_current_user
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


class ChatOut(BaseModel):
    reply: str
    citations: list[dict] = []
    available: bool


class AskIn(BaseModel):
    question: str
    project_id: int | None = None


class AskOut(BaseModel):
    answer: str
    mode: str  # "llm" | "extractive"
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


def _fmt_project(p: Project) -> str:
    stage = STAGE_LABELS.get(p.stage or "", p.stage or "Unknown")
    lines = [
        f"Project: {p.pr_number} — {p.title}",
        f"  Stage: {stage}",
        f"  Location: {p.location or 'N/A'}",
        f"  PI: {p.pi_name or 'N/A'} ({p.pi_email or 'N/A'})",
        f"  Funding: {p.funding_source or 'N/A'}",
        f"  Disposition: {p.disposition or 'N/A'}",
        f"  Created: {p.created_at.strftime('%Y-%m-%d') if p.created_at else 'N/A'}",
    ]
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


def _build_project_context(question: str, project_id: int | None, db: Session) -> tuple[str, list[dict]]:
    """
    Build a context string from the database relevant to the question.
    Returns (context_text, sources_list).
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
        context_parts.append(proj_text)
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

    # 4. If no specific PR matched, provide a project listing for generic queries
    if not matched_projects and not project_id:
        keyword_lower = question.lower()
        search_terms = [w for w in keyword_lower.split() if len(w) > 3 and w not in {"what", "when", "where", "which", "that", "this", "with", "from", "have", "been", "about", "status"}]
        if search_terms:
            all_projects = db.query(Project).order_by(Project.updated_at.desc()).limit(50).all()
            relevant = [
                p for p in all_projects
                if any(term in (p.title or "").lower() or term in (p.pr_number or "").lower() or term in (p.description or "").lower()
                       for term in search_terms)
            ]
            if relevant:
                context_parts.append(f"Relevant projects matching your query:")
                for p in relevant[:5]:
                    context_parts.append(_fmt_project(p))
                    sources.append({"filename": f"Project {p.pr_number}", "snippet": f"{p.title} — {STAGE_LABELS.get(p.stage or '', p.stage or '')}"})

    return "\n".join(context_parts), sources


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the KAUST IHP (Infrastructure & Housing Projects) shadow engineer assistant.

You have access to live project data from the IHP platform database, including:
- Projects (PR numbers, titles, stages, locations, PI names)
- Minutes of Meeting (MOM) records
- Engineering Assessment Reports (EAR)
- Scope of Work (SOW) records
- Material tracking and delivery status
- Work permits
- ICR handoffs and approvals
- Construction progress
- Closeout records

When answering:
1. ALWAYS refer to projects by their PR number (e.g., PR-12623)
2. Report exact data from the context provided — do not guess or make up values
3. If a PR number is not found in the database context, say so clearly
4. Be concise and structured (use bullet points for multiple items)
5. "PR=XXXXX" in a user question means they are asking about project PR-XXXXX

Stage progression: Intake → MOM Confirmed → EAR Review → Disposition → SOW/BOQ → ICR → Construction → Closeout
"""


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatOut)
def chat(
    body: ChatIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Project-scoped Q&A over the corpus + memory."""
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
    db_context, sources = _build_project_context(body.message, body.project_id, db)
    hits = retrieval.search(body.message, db, k=5)
    citations = [{"filename": h["filename"], "snippet": h["text"][:200]} for h in hits]

    user_content = body.message
    if db_context:
        user_content = f"Database context:\n{db_context}\n\nQuestion: {body.message}"

    reply = provider.chat(
        [{"role": "user", "content": user_content}],
        system=SYSTEM_PROMPT,
    )
    return ChatOut(
        reply=reply or "(no response from provider)",
        citations=citations + sources[:3],
        available=True,
    )


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
    is_available, reason = provider.available()
    if not is_available:
        return AskOut(
            answer=(
                "The AI provider is currently offline. "
                "Configure AI_PROVIDER and the matching API key in .env to enable it."
                + (f" (reason: {reason})" if reason else "")
            ),
            mode="extractive",
            sources=[],
        )

    # Build live database context
    db_context, db_sources = _build_project_context(body.question, body.project_id, db)

    # Also do corpus retrieval
    hits = retrieval.search(body.question, db, k=5)
    corpus_sources = [{"filename": h["filename"], "snippet": h["text"][:200]} for h in hits]

    # Build user message with all context
    user_content = body.question
    context_blocks = []
    if db_context:
        context_blocks.append(f"[Live project database context]\n{db_context}")
    if hits:
        corpus_text = "\n\n".join(f"[{h['filename']}]: {h['text']}" for h in hits)
        context_blocks.append(f"[Knowledge base documents]\n{corpus_text}")

    if context_blocks:
        user_content = "\n\n".join(context_blocks) + f"\n\nQuestion: {body.question}"

    reply = provider.chat(
        [{"role": "user", "content": user_content}],
        system=SYSTEM_PROMPT,
    )

    all_sources = db_sources + corpus_sources
    return AskOut(
        answer=reply or "(no response from provider)",
        mode="llm",
        sources=all_sources[:6],
    )


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
