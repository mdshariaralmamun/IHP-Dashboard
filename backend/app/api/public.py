"""Public endpoints - everything reachable without an account.

The site root is a read-only dashboard (aggregate numbers only: no PR numbers,
no names, no documents) plus a single action: ask for access. Everything else in
the platform stays behind authentication, and accounts exist only when an admin
approves a request from the in-app inbox.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import REQUESTABLE_ROLES, AccessRequest, User
from ..services import emailer

router = APIRouter(prefix="/public", tags=["public"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

#: Simple in-process throttle: n requests per window per client IP. The public
#: form is unauthenticated, so it needs *some* abuse protection; the platform
#: runs a single backend process, which makes this sufficient.
_RATE_LIMIT = 5
_RATE_WINDOW_SECONDS = 3600
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Behind nginx-proxy-manager / Cloudflare the real client is in the headers.
    for header in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    bucket = _hits[ip]
    while bucket and now - bucket[0] > _RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        raise HTTPException(
            429, "Too many access requests from this network. Try again later."
        )
    bucket.append(now)


@router.get("/dashboard")
def public_dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Aggregate portfolio metrics for the public dashboard.

    Deliberately counts only: no project identifiers, people or documents are
    exposed to anonymous visitors.
    """
    from ..ai import facts as facts_mod

    pack = facts_mod.collect(db)

    def counts(counter: Any) -> dict[str, int]:
        return {str(k): int(v) for k, v in counter.most_common()}

    windows = {
        "overdue": len(pack["overdue"]),
        "this_week": len(pack["this_week"]),
        "on_hold": len(pack["on_hold"]),
        "high_risk": len(pack["high_risk"]),
        "behind_plan": len(pack["behind_plan"]),
        "design_gate": len(pack["design_gate"]),
    }
    return {
        "totals": {
            "projects": pack["total"],
            "scheduled": len(pack["scheduled"]),
            "without_planner_date": len(pack["unscheduled"]),
        },
        "by_division": counts(pack["by_division"]),
        "by_stage": counts(pack["by_stage"]),
        "windows": windows,
        "planner_sync": pack["sync"],
        "generated_at": pack["today"],
        "requestable_roles": [
            {"value": value, "label": label}
            for value, label in REQUESTABLE_ROLES.items()
        ],
    }


class AccessRequestIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=200)
    phone: str | None = Field(default=None, max_length=64)
    company: str | None = Field(default=None, max_length=200)
    requested_role: str = Field(default="viewer", max_length=32)
    message: str | None = Field(default=None, max_length=2000)


@router.post("/access-request")
def create_access_request(
    body: AccessRequestIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a visitor's request for an account and notify the admins."""
    ip = _client_ip(request)
    _check_rate_limit(ip)

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if body.requested_role not in REQUESTABLE_ROLES:
        raise HTTPException(400, "Choose one of the listed roles.")

    existing = db.scalars(
        select(AccessRequest)
        .where(AccessRequest.email == email, AccessRequest.status == "pending")
        .order_by(AccessRequest.id.desc())
    ).first()

    if existing is not None:
        # Refresh the pending request instead of piling up duplicates.
        existing.full_name = body.full_name.strip()
        existing.phone = (body.phone or "").strip() or None
        existing.company = (body.company or "").strip() or None
        existing.requested_role = body.requested_role
        existing.message = (body.message or "").strip() or None
        db.commit()
        return {
            "ok": True,
            "reference": f"REQ-{existing.id}",
            "message": "Your earlier request is already waiting for approval.",
        }

    row = AccessRequest(
        full_name=body.full_name.strip(),
        email=email,
        phone=(body.phone or "").strip() or None,
        company=(body.company or "").strip() or None,
        requested_role=body.requested_role,
        message=(body.message or "").strip() or None,
        source_ip=ip,
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    _notify_admins(db, row)
    return {
        "ok": True,
        "reference": f"REQ-{row.id}",
        "message": (
            "Request received. An administrator reviews it in the platform and "
            "sends you a personal access link."
        ),
    }


def _notify_admins(db: Session, row: AccessRequest) -> None:
    """Best-effort email to the admins; the in-app inbox is the source of truth."""
    label = REQUESTABLE_ROLES.get(row.requested_role, row.requested_role)
    body = "\n".join([
        "A new access request is waiting in the platform inbox.",
        "",
        f"Name:   {row.full_name}",
        f"Email:  {row.email}",
        f"Phone:  {row.phone or '-'}",
        f"Org:    {row.company or '-'}",
        f"Role:   {label}",
        f"Note:   {row.message or '-'}",
        f"Source: {row.source_ip or '-'}",
        "",
        "Open Admin -> Access requests to approve or reject it.",
    ])
    try:
        admins = db.scalars(
            select(User).where(User.role == "admin", User.is_active.is_(True))
        ).all()
        for admin in admins:
            if admin.email:
                emailer.send_email(admin.email, "IHP: new access request", body)
    except Exception:  # noqa: BLE001 - notification must never fail the request
        pass
