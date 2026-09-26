"""Authentication and role/trade enforcement dependencies."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Resolve the JWT bearer token to an active user, else 401."""
    username = decode_access_token(token)
    if not username:
        raise _credentials_exception
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise _credentials_exception
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return user


# --- Capabilities -------------------------------------------------------------
# Fine-grained permissions checked via require_capability(). A user's effective
# set is their stored `permissions` list when set, else the role defaults.
CAP_PROJECTS_CREATE = "projects.create"
CAP_PROJECTS_EDIT = "projects.edit"
CAP_PROJECTS_DELETE = "projects.delete"
CAP_ATTACHMENTS_UPLOAD = "attachments.upload"
CAP_ATTACHMENTS_DELETE = "attachments.delete"
CAP_MOM_MANAGE = "mom.manage"
CAP_MOM_AGENDA = "mom.agenda"
CAP_USERS_MANAGE = "users.manage"
CAP_DISPOSITION_MANAGE = "disposition.manage"
CAP_EAR_INPUT = "ear.input"  # submit trade proposal under EAR
CAP_EAR_MANAGE = "ear.manage"  # approve/manage EAR record
CAP_SOW_MANAGE = "sow.manage"
CAP_BOQ_MANAGE = "boq.manage"
CAP_MTO_MANAGE = "mto.manage"  # design + construction MTO
CAP_PROCUREMENT_MANAGE = "procurement.manage"
CAP_WORK_PERMIT_MANAGE = "work_permit.manage"
CAP_CONSTRUCTION_MANAGE = "construction.manage"
CAP_CLOSEOUT_MANAGE = "closeout.manage"
CAP_ICR_HANDOFF = "icr.handoff"  # record ICR-branch hand-off milestones
CAP_AI_PROPOSAL_ACCEPT = "ai.proposal.accept"  # accept/edit/reject AI drafts
CAP_DATA_MANAGE = "data.manage"  # create/edit/delete source-tagged data points
CAP_DATA_CONFIRM = "data.confirm"  # CONFIRM: promote TBC/ASSUMPTION -> PLANNER

ALL_CAPABILITIES: frozenset[str] = frozenset(
    {
        CAP_PROJECTS_CREATE,
        CAP_PROJECTS_EDIT,
        CAP_PROJECTS_DELETE,
        CAP_ATTACHMENTS_UPLOAD,
        CAP_ATTACHMENTS_DELETE,
        CAP_MOM_MANAGE,
        CAP_MOM_AGENDA,
        CAP_USERS_MANAGE,
        CAP_DISPOSITION_MANAGE,
        CAP_EAR_INPUT,
        CAP_EAR_MANAGE,
        CAP_SOW_MANAGE,
        CAP_BOQ_MANAGE,
        CAP_MTO_MANAGE,
        CAP_PROCUREMENT_MANAGE,
        CAP_WORK_PERMIT_MANAGE,
        CAP_CONSTRUCTION_MANAGE,
        CAP_CLOSEOUT_MANAGE,
        CAP_ICR_HANDOFF,
        CAP_AI_PROPOSAL_ACCEPT,
        CAP_DATA_MANAGE,
        CAP_DATA_CONFIRM,
    }
)

#: Capabilities granted by role when User.permissions is NULL.
ROLE_DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ALL_CAPABILITIES,
    # Trade users contribute their discipline input into EAR / SOW / MTO.
    "trade": frozenset(
        {CAP_MOM_AGENDA, CAP_EAR_INPUT, CAP_MTO_MANAGE, CAP_AI_PROPOSAL_ACCEPT}
    ),
    # Planning drives the disposition, EAR, SOW, BOQ, and procurement records.
    "planning": frozenset(
        {
            CAP_MOM_AGENDA,
            CAP_DISPOSITION_MANAGE,
            CAP_EAR_MANAGE,
            CAP_SOW_MANAGE,
            CAP_BOQ_MANAGE,
            CAP_MTO_MANAGE,
            CAP_PROCUREMENT_MANAGE,
            CAP_AI_PROPOSAL_ACCEPT,
            # Planner owns the §3 traceability engine; CONFIRM is the
            # Planner-only promotion of a pending tag to PLANNER.
            CAP_DATA_MANAGE,
            CAP_DATA_CONFIRM,
        }
    ),
    # Construction managers own work permits, construction execution, and
    # closeout. They also reconcile the construction MTO against design.
    "construction_manager": frozenset(
        {
            CAP_MOM_AGENDA,
            CAP_MTO_MANAGE,
            CAP_WORK_PERMIT_MANAGE,
            CAP_CONSTRUCTION_MANAGE,
            CAP_CLOSEOUT_MANAGE,
            CAP_ICR_HANDOFF,
            CAP_AI_PROPOSAL_ACCEPT,
        }
    ),
    "team_member": frozenset({CAP_MOM_AGENDA}),
    # Read-only: dashboards, register and documents, but no write capability.
    # This is what the public "request access" form offers by default.
    "viewer": frozenset(),
}


def effective_permissions(user: User) -> set[str]:
    """The user's exact capability set: stored override if present, else role defaults."""
    if user.permissions is not None:
        return set(user.permissions)
    return set(ROLE_DEFAULT_PERMISSIONS.get(user.role, set()))


def require_capability(capability: str) -> Callable:
    """Dependency factory requiring one capability in the user's effective set."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if capability not in effective_permissions(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {capability}",
            )
        return user

    return dependency


def require_roles(*roles: str) -> Callable:
    """Dependency factory allowing any of the given roles.

    Stage 1 only needs admin-vs-authenticated, but later stages use this for
    e.g. require_roles("planning", "admin") or trade-scoped checks.
    """

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user

    return dependency


def require_trade(*trades: str) -> Callable:
    """Dependency factory restricting access to users of given trades.

    Reserved for later stages (EAR/SOW/MTO reviews per discipline). Admins
    pass through; non-admins must carry one of the listed trades.
    """

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role == "admin":
            return user
        if user.trade not in trades:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of trades: {', '.join(trades)}",
            )
        return user

    return dependency
