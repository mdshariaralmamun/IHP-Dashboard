"""Admin endpoints: user management (users.manage capability)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.rbac import CAP_USERS_MANAGE, require_capability
from ..core.security import hash_password
from ..db import get_db
from ..models import Attachment, AuditLog, MomRecord, Project, User
from ..schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


@router.post("/users", response_model=UserOut)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' already exists",
        )
    user = User(
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        trade=payload.trade,
        title=payload.title,
        permissions=payload.permissions,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    return db.scalars(select(User).order_by(User.id)).all()


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    """Apply only the provided fields. A role change away from "trade" clears
    the trade unless a trade is explicitly provided in the same request."""
    user = get_user_or_404(db, user_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("full_name", "email", "title"):
        if field in data:
            setattr(user, field, data[field])
    if "password" in data:
        user.hashed_password = hash_password(data["password"])
    if "role" in data:
        user.role = data["role"]
        if data["role"] != "trade" and "trade" not in data:
            user.trade = None
    if "trade" in data:
        user.trade = data["trade"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "permissions" in data:
        # Explicit null restores the role defaults; a list (even []) is exact.
        user.permissions = data["permissions"]

    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_capability(CAP_USERS_MANAGE)),
):
    user = get_user_or_404(db, user_id)

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    if user.role == "admin" and user.is_active:
        active_admins = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
        if (active_admins or 0) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the last active admin",
            )
    has_records = any(
        db.scalar(select(model.id).where(column == user.id).limit(1)) is not None
        for model, column in (
            (Project, Project.created_by_id),
            (Attachment, Attachment.uploaded_by_id),
            (MomRecord, MomRecord.updated_by_id),
            (AuditLog, AuditLog.user_id),
        )
    )
    if has_records:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User has records; deactivate instead",
        )

    db.delete(user)
    db.commit()
