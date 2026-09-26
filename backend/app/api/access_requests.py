"""Access-request inbox: the admin decides who gets into the platform.

Approving a request creates the account and returns a one-time invite link that
the admin sends to the person; opening it lets them set a password. Rejecting
keeps the record with a note. Nothing here is reachable without the
users.manage capability.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_USERS_MANAGE, get_current_user, require_capability
from ..core.security import hash_password
from ..db import get_db
from ..models import REQUESTABLE_ROLES, AccessRequest, User

router = APIRouter(prefix="/admin/access-requests", tags=["access_requests"])

#: How long an invite link stays valid.
INVITE_DAYS = 14

APPROVABLE_ROLES = set(REQUESTABLE_ROLES) | {"admin"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _shape(row: AccessRequest, invite_url_base: str | None = None) -> dict[str, Any]:
    invite_url = (
        f"{invite_url_base.rstrip('/')}/invite/{row.invite_token}"
        if invite_url_base and row.invite_token
        else None
    )
    return {
        "id": row.id,
        "reference": f"REQ-{row.id}",
        "full_name": row.full_name,
        "email": row.email,
        "phone": row.phone,
        "company": row.company,
        "requested_role": row.requested_role,
        "requested_role_label": REQUESTABLE_ROLES.get(
            row.requested_role, row.requested_role
        ),
        "message": row.message,
        "status": row.status,
        "decision_note": row.decision_note,
        "created_at": _iso(row.created_at),
        "decided_at": _iso(row.decided_at),
        "invite_token": row.invite_token,
        "invite_url": invite_url,
        "invite_expires_at": _iso(row.invite_expires_at),
        "invite_used_at": _iso(row.invite_used_at),
        "user_id": row.user_id,
        "source_ip": row.source_ip,
    }


@router.get("")
def list_access_requests(
    status: str | None = Query(default=None, description="pending|approved|rejected"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """The inbox: newest first, with the counters the UI shows as badges."""
    stmt = select(AccessRequest).order_by(AccessRequest.id.desc())
    if status:
        stmt = stmt.where(AccessRequest.status == status)
    rows = db.scalars(stmt.limit(limit)).all()
    counts = {
        value: int(total)
        for value, total in db.execute(
            select(AccessRequest.status, func.count(AccessRequest.id)).group_by(
                AccessRequest.status
            )
        ).all()
    }
    return {
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0),
        "rejected": counts.get("rejected", 0),
        "roles": [
            {"value": value, "label": label}
            for value, label in REQUESTABLE_ROLES.items()
        ],
        "items": [_shape(row) for row in rows],
    }


@router.get("/notifications")
def notifications(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Small badge payload for the header bell."""
    pending = db.scalar(
        select(func.count(AccessRequest.id)).where(AccessRequest.status == "pending")
    ) or 0
    latest = db.scalars(
        select(AccessRequest)
        .where(AccessRequest.status == "pending")
        .order_by(AccessRequest.id.desc())
        .limit(5)
    ).all()
    return {
        "pending_access_requests": int(pending),
        "latest": [
            {
                "id": row.id,
                "full_name": row.full_name,
                "email": row.email,
                "requested_role": row.requested_role,
                "created_at": _iso(row.created_at),
            }
            for row in latest
        ],
    }


def _unique_username(db: Session, email: str, full_name: str) -> str:
    base = (email.split("@")[0] or full_name or "user").strip().lower()
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")[:40] or "user"
    candidate = base
    suffix = 1
    while db.scalar(select(User).where(User.username == candidate)) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


class ApproveIn(BaseModel):
    role: str | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.post("/{request_id}/approve")
def approve_access_request(
    request_id: int,
    body: ApproveIn | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Create (or link) the account and mint a one-time invite link.

    The body is optional: approving as-requested needs only the request id.
    """
    body = body or ApproveIn()
    row = db.get(AccessRequest, request_id)
    if row is None:
        raise HTTPException(404, "Access request not found")
    if row.status == "approved" and row.invite_token and not row.invite_used_at:
        return {"ok": True, "already_approved": True, **_shape(row)}

    role = (body.role or row.requested_role or "viewer").strip()
    if role not in APPROVABLE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(APPROVABLE_ROLES)}")

    user = db.scalar(select(User).where(func.lower(User.email) == row.email))
    if user is None:
        user = db.scalar(
            select(User).where(User.username == _unique_username(db, row.email, row.full_name))
        )
    if user is None:
        user = User(
            username=_unique_username(db, row.email, row.full_name),
            full_name=row.full_name,
            email=row.email,
            role=role,
            # Placeholder password: the account is unusable until the invitee
            # sets their own through the invite link.
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.role = role
        if not user.full_name:
            user.full_name = row.full_name

    row.status = "approved"
    row.requested_role = role
    row.user_id = user.id
    row.decided_by_id = admin.id
    row.decided_at = datetime.now(timezone.utc)
    row.decision_note = (body.note or "").strip() or None
    row.invite_token = secrets.token_urlsafe(24)
    row.invite_expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)
    row.invite_used_at = None
    db.commit()
    db.refresh(row)
    return {"ok": True, "request": _shape(row), "username": user.username}


@router.post("/{request_id}/reissue")
def reissue_invite(
    request_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Mint a fresh invite link (the old one stops working)."""
    row = db.get(AccessRequest, request_id)
    if row is None:
        raise HTTPException(404, "Access request not found")
    if row.status != "approved":
        raise HTTPException(400, "Approve the request first")
    row.invite_token = secrets.token_urlsafe(24)
    row.invite_expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)
    row.invite_used_at = None
    row.decided_by_id = admin.id
    db.commit()
    db.refresh(row)
    return {"ok": True, "request": _shape(row)}


class RejectIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


@router.post("/{request_id}/reject")
def reject_access_request(
    request_id: int,
    body: RejectIn | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    body = body or RejectIn()
    row = db.get(AccessRequest, request_id)
    if row is None:
        raise HTTPException(404, "Access request not found")
    row.status = "rejected"
    row.decision_note = (body.note or "").strip() or None
    row.decided_by_id = admin.id
    row.decided_at = datetime.now(timezone.utc)
    row.invite_token = None
    row.invite_expires_at = None
    db.commit()
    db.refresh(row)
    return {"ok": True, "request": _shape(row)}
