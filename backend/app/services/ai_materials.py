"""AI-coordinated materials suggestion (master prompt §AI coordination).

Drafts a trade-wise materials list + initial budget for a project from:

  1. the project request (title/description),
  2. the assessment (EAR summary + trade proposals) and SOW scope,
  3. the materials master list (master_pricing — the Planner's price file).

Two engines, mirroring the EAR AI cross-check pattern:

- ``ai``      — the LLM picks from keyword-scored master candidates and
                estimates quantities from the scope.
- ``keyword`` — deterministic fallback (provider offline / bad JSON):
                the top keyword-scored candidates per trade, qty 1.

Every generated item is a SUGGESTION — an ASSUMPTION under the §3
traceability rules — until a Planner accepts the proposal; acceptance
creates design BoqMtoItem rows priced from the master list. Nothing is
ever written into a BOQ by the AI itself.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import provider
from ..models import (
    AiMaterialsProposal,
    BoqMtoItem,
    EarRecord,
    MasterPricing,
    Project,
    SowRecord,
    User,
)
from . import runtime_settings, workflow
from .price_master import infer_trade

_STOPWORDS = {
    "the", "and", "with", "for", "from", "this", "that", "will", "shall",
    "including", "include", "includes", "required", "existing", "new",
    "project", "room", "area", "level", "building", "works", "work",
    "installation", "install", "installation,", "supply", "provide",
    "kaust", "ihp", "scope", "per", "all", "any", "into", "within",
}
_TOKEN_RE = re.compile(r"[a-z0-9/\-]+")

#: Per-trade / overall candidate caps fed to the LLM (bounded prompt).
PER_TRADE_LIMIT = 8
CANDIDATE_CAP = 48
AI_PICK_CAP = 30


def build_project_brief(db: Session, project: Project) -> dict:
    """Scope text + trades-in-scope from PR, EAR (assessment), and SOW."""
    parts = [f"{project.title}", project.description or ""]
    trades: set[str] = set()

    ear = db.scalar(
        select(EarRecord)
        .where(EarRecord.project_id == project.id)
        .order_by(EarRecord.id.desc())
    )
    if ear is not None:
        if ear.summary:
            parts.append(ear.summary)
        for ti in getattr(ear, "trade_inputs", []) or []:
            code = infer_trade(ti.trade or "")
            if code:
                trades.add(code)
            parts.append(f"{ti.trade}: {ti.proposal} {ti.comments or ''}")

    sow = db.scalar(
        select(SowRecord)
        .where(SowRecord.project_id == project.id)
        .order_by(SowRecord.id.desc())
    )
    if sow is not None and sow.scope_text:
        parts.append(sow.scope_text)
        if isinstance(sow.trade_sections, dict):
            for trade in sow.trade_sections.get("trades") or []:
                code = infer_trade(trade.get("name", ""))
                if code:
                    trades.add(code)

    return {
        "title": project.title,
        "location": project.location or "",
        "scope_text": "\n".join(p for p in parts if p).strip(),
        "trades": sorted(trades),
    }


def _scope_tokens(scope_text: str) -> list[str]:
    tokens = [
        t for t in _TOKEN_RE.findall((scope_text or "").lower())
        if len(t) >= 3 and t not in _STOPWORDS
    ]
    return list(dict.fromkeys(tokens))  # unique, keep order


def keyword_candidates(
    db: Session, brief: dict, trades: list[str] | None = None,
    per_trade: int = PER_TRADE_LIMIT, cap: int = CANDIDATE_CAP,
) -> list[dict]:
    """Score active master items against the scope, trade-wise top-N."""
    tokens = _scope_tokens(brief["scope_text"])
    if not tokens:
        return []
    wanted = set(trades) if trades else (
        set(brief["trades"]) if brief["trades"] else None)

    rows = db.scalars(
        select(MasterPricing).where(MasterPricing.is_active.is_(True))
    ).all()

    scored: list[tuple[int, dict]] = []
    for row in rows:
        desc = (row.description or "").lower()
        score = sum(1 for t in tokens if t in desc)
        if score == 0:
            continue
        if wanted is not None and row.trade not in wanted:
            continue
        scored.append((score, {
            "item_code": row.item_code,
            "description": row.description,
            "trade": row.trade,
            "unit": row.unit,
            "unit_rate": row.base_unit_rate,
            "_score": score,
        }))

    # Trade-wise top-N, then overall cap (stable: score desc, code asc)
    by_trade: dict[str, list[tuple[int, dict]]] = {}
    for entry in scored:
        by_trade.setdefault(entry[1]["trade"] or "general", []).append(entry)
    picked: list[dict] = []
    for trade_key in sorted(by_trade):
        group = sorted(by_trade[trade_key], key=lambda e: (-e[0], e[1]["item_code"]))
        picked.extend(e[1] for e in group[:per_trade])
    picked.sort(key=lambda c: (-c["_score"], c["item_code"]))
    for c in picked:
        c.pop("_score", None)
    return picked[:cap]


def _extract_json_array(text: str) -> list | None:
    """First JSON array in an LLM reply (tolerates code fences/prose)."""
    clean = text.strip()
    if "```" in clean:
        for part in text.split("```"):
            body = part.strip()
            if body.startswith("json"):
                body = body[4:].strip()
            if body.startswith("["):
                clean = body
                break
    start = clean.find("[")
    if start == -1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(clean[start:])
        return value if isinstance(value, list) else None
    except json.JSONDecodeError:
        return None


def ai_select(brief: dict, candidates: list[dict]) -> list[dict] | None:
    """LLM coordination: pick items + estimate quantities. None = degrade."""
    available, _ = provider.available()
    if not available or not candidates:
        return None

    candidate_lines = "\n".join(
        f"{c['item_code']} | {c['trade'] or 'general'} | {c['description'][:90]} "
        f"| per {c['unit']} @ {c['unit_rate']} SAR"
        for c in candidates
    )
    prompt = (
        f"PROJECT REQUEST / ASSESSMENT SCOPE:\n{brief['title']}\n"
        f"Location: {brief['location']}\n{brief['scope_text'][:2500]}\n\n"
        f"MATERIALS MASTER LIST (item_code | trade | description | unit | rate SAR):\n"
        f"{candidate_lines}\n\n"
        "Select the materials needed to deliver this scope, trade-wise. "
        "Return ONLY a JSON array, one object per pick: "
        '{"item_code": "<from the list>", "qty": <number or null>, '
        '"reason": "<short>"}}. '
        "Estimate qty from the scope when stated; otherwise null. "
        "Do not invent item codes; skip items irrelevant to the scope."
    )
    try:
        reply = provider.chat(
            [{"role": "user", "content": prompt}],
            system=(
                "You are the KAUST IHP materials coordinator. "
                "Return ONLY a valid JSON array, no prose."
            ),
        )
    except Exception:  # noqa: BLE001 — provider errors degrade, never crash
        return None
    if not reply:
        return None

    picks = _extract_json_array(reply)
    if not picks:
        return None
    valid_codes = {c["item_code"] for c in candidates}
    by_code = {c["item_code"]: c for c in candidates}
    result = []
    seen: set[str] = set()
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        code = str(pick.get("item_code", ""))
        if code not in valid_codes or code in seen:
            continue
        seen.add(code)
        qty = pick.get("qty")
        if not isinstance(qty, (int, float)) or qty <= 0:
            qty = 1.0  # qty unknown -> minimum viable quantity, flagged below
            qty_estimated = True
        else:
            qty_estimated = False
        base = by_code[code]
        result.append({
            "item_code": code,
            "description": base["description"],
            "trade": base["trade"],
            "unit": base["unit"],
            "unit_rate": base["unit_rate"],
            "qty": float(qty),
            "reason": str(pick.get("reason", ""))[:200]
            + (" (qty not stated in scope — defaulted to 1)" if qty_estimated else ""),
            "origin": "ai",
        })
        if len(result) >= AI_PICK_CAP:
            break
    return result or None


def generate_proposal(
    db: Session, project: Project, user: User,
    stage_target: str = "MTO", trades: list[str] | None = None,
) -> AiMaterialsProposal:
    """Draft + persist a proposal. mode=ai when the LLM coordinated the
    selection, mode=keyword when the deterministic engine stood in."""
    brief = build_project_brief(db, project)
    candidates = keyword_candidates(db, brief, trades=trades)

    ai_picks = ai_select(brief, candidates)
    if ai_picks is not None:
        from ..core.config import get_settings
        model = runtime_settings.effective(
            "AI_CHAT_MODEL", get_settings().AI_CHAT_MODEL)
        mode, items = "ai", ai_picks
    else:
        mode, model = "keyword", None
        items = [{
            "item_code": c["item_code"],
            "description": c["description"],
            "trade": c["trade"],
            "unit": c["unit"],
            "unit_rate": c["unit_rate"],
            "qty": 1.0,
            "reason": "matched scope keywords (AI provider offline or unusable)",
            "origin": "keyword",
        } for c in candidates]

    pv = runtime_settings.project_variables()
    subtotal = sum(i["qty"] * i["unit_rate"] for i in items)
    vat = subtotal * pv["VAT_RATE"]

    proposal = AiMaterialsProposal(
        project_id=project.id,
        stage_target=stage_target,
        status="draft",
        mode=mode,
        items=items,
        subtotal_sar=round(subtotal, 2),
        vat_sar=round(vat, 2),
        total_sar=round(subtotal + vat, 2),
        model=model,
        created_by_id=user.id,
    )
    db.add(proposal)
    db.flush()
    workflow.log_action(
        db, user, "ai_materials:proposed", project,
        {"proposal_id": proposal.id, "mode": mode, "items": len(items),
         "stage_target": stage_target},
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def accept_proposal(db: Session, proposal: AiMaterialsProposal, user: User) -> list[BoqMtoItem]:
    """Planner accepts: suggestion lines become design BOQ/MTO rows,
    priced from the master list. Returns the created items."""
    if proposal.status != "draft":
        raise ValueError(f"Proposal is {proposal.status}, not draft")

    project = db.get(Project, proposal.project_id)
    created: list[BoqMtoItem] = []
    for item in proposal.items or []:
        qty, rate = float(item.get("qty", 0)), float(item.get("unit_rate", 0))
        if qty <= 0 or rate <= 0:
            continue  # unpriced/unquantified suggestions stay suggestions
        trade = item.get("trade") or infer_trade(item.get("description", "")) or "general"
        created.append(BoqMtoItem(
            project_id=project.id,
            trade=trade,
            item_code=item["item_code"],
            description=item["description"],
            unit=item.get("unit", "EA"),
            quantity=qty,
            unit_rate=rate,
            total_rate=qty * rate,
            mto_kind="design",
            delivery_status="pending",
        ))
    db.add_all(created)

    proposal.status = "accepted"
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by_id = user.id
    workflow.log_action(
        db, user, "ai_materials:accepted", project,
        {"proposal_id": proposal.id, "boq_items_created": len(created)},
    )
    db.commit()
    return created


def reject_proposal(db: Session, proposal: AiMaterialsProposal, user: User) -> AiMaterialsProposal:
    if proposal.status != "draft":
        raise ValueError(f"Proposal is {proposal.status}, not draft")
    proposal.status = "rejected"
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by_id = user.id
    project = db.get(Project, proposal.project_id)
    workflow.log_action(
        db, user, "ai_materials:rejected", project, {"proposal_id": proposal.id},
    )
    db.commit()
    db.refresh(proposal)
    return proposal
