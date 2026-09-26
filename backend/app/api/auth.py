"""Auth endpoints: OAuth2 password login + current-user info + profile
management + the public invite links that finish an approved access request."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import get_current_user
from ..core.security import create_access_token, verify_password, hash_password
from ..db import get_db
from ..models import AccessRequest, User
from ..schemas import TokenOut, UserOut, ProfileUpdate, ChangePassword
from ..services.rbac_service import get_user_roles, get_all_user_permissions

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = db.scalar(select(User).where(User.username == form_data.username))
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account disabled"
        )
    return TokenOut(access_token=create_access_token(user.username))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/profile", response_model=UserOut)
def update_profile(
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current user's own profile (name, email, title)."""
    if body.full_name is not None:
        current_user.full_name = body.full_name
    if body.email is not None:
        current_user.email = body.email
    if body.title is not None:
        current_user.title = body.title
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password")
def change_password(
    body: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password after verifying the old one."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters",
        )
    current_user.hashed_password = hash_password(body.new_password)
    db.commit()
    return {"detail": "Password changed successfully"}


# ---------------------------------------------------------------------------
# Invite links (public)
# ---------------------------------------------------------------------------


class InvitePasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=200)


def _invite_row(db: Session, token: str) -> AccessRequest:
    row = db.scalar(select(AccessRequest).where(AccessRequest.invite_token == token))
    if row is None:
        raise HTTPException(404, "This invite link is not valid.")
    if row.invite_used_at is not None:
        raise HTTPException(410, "This invite link has already been used.")
    expires = row.invite_expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(410, "This invite link has expired. Request a new one.")
    return row


@router.get("/invite/{token}")
def invite_info(token: str, db: Session = Depends(get_db)):
    """Details for the set-password page (no login required)."""
    row = _invite_row(db, token)
    user = db.get(User, row.user_id) if row.user_id else None
    return {
        "valid": True,
        "full_name": row.full_name,
        "email": row.email,
        "role": row.requested_role,
        "username": user.username if user else "",
        "expires_at": row.invite_expires_at.isoformat() if row.invite_expires_at else None,
    }


@router.post("/invite/{token}")
def invite_set_password(
    token: str,
    body: InvitePasswordIn,
    db: Session = Depends(get_db),
):
    """Set the password for the invited account and return a login token."""
    row = _invite_row(db, token)
    user = db.get(User, row.user_id) if row.user_id else None
    if user is None:
        raise HTTPException(409, "The account for this invite no longer exists.")

    user.hashed_password = hash_password(body.password)
    user.is_active = True
    row.invite_used_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": True,
        "username": user.username,
        "access_token": create_access_token(user.username),
        "token_type": "bearer",
    }


@router.get("/my-roles")
def my_roles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's RBAC roles and effective permissions."""
    roles = get_user_roles(db, current_user.id)
    permissions = get_all_user_permissions(db, current_user.id)

    return {
        "user_id": current_user.id,
        "roles": [
            {
                "id": r.id,
                "name": r.name,
                "display_name": r.display_name,
                "discipline": r.discipline,
                "color": r.color,
            }
            for r in roles
        ],
        "effective_permissions": permissions,
    }
