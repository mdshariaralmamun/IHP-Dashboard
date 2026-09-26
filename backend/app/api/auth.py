"""Auth endpoints: OAuth2 password login + current-user info + profile management."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import get_current_user
from ..core.security import create_access_token, verify_password, hash_password
from ..db import get_db
from ..models import User
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
