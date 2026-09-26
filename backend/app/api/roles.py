"""API endpoints for role and permission management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..core.rbac import require_admin, get_current_user
from ..db import get_db
from ..models import User
from ..rbac_models import DISCIPLINES, RESOURCE_TYPES
from ..schemas_rbac import (
    RoleCreate,
    RoleUpdate,
    RoleResponse,
    RoleListItem,
    PermissionSet,
    BulkPermissionUpdate,
    RoleStats,
    RBACSystemInfo,
    DisciplineInfo,
    ResourceTypeInfo,
)
from ..services import rbac_service

router = APIRouter(prefix="/api/roles", tags=["roles"])


# Resource type display names and descriptions
RESOURCE_DISPLAY_INFO = {
    "projects": ("Projects", "Project records and management"),
    "mom": ("Minutes of Meeting", "Meeting records and agenda"),
    "ear": ("EAR", "Engineering Assessment Reports"),
    "sow": ("SOW", "Scope of Work documents"),
    "boq": ("BOQ", "Bill of Quantities"),
    "mto": ("Design MTO", "Design Material Take-Off"),
    "construction_mto": ("Construction MTO", "Construction Material Take-Off"),
    "procurement": ("Procurement", "Procurement management"),
    "work_permit": ("Work Permits", "Work permit and safety approvals"),
    "construction": ("Construction", "Construction execution records"),
    "closeout": ("Closeout", "Project closeout and handover"),
    "icr_handoff": ("ICR Handoff", "ICR project handoffs"),
    "users": ("Users", "User account management"),
    "roles": ("Roles", "Role and permission management"),
    "attachments": ("Attachments", "Document attachments"),
    "data_points": ("Data Points", "Project data traceability"),
    "ai_proposals": ("AI Proposals", "AI-generated materials proposals"),
    "master_pricing": ("Master Pricing", "Master pricing database"),
    "reports": ("Reports", "Report generation and access"),
    "audit_logs": ("Audit Logs", "System audit trail"),
}


@router.get("/system-info", response_model=RBACSystemInfo)
def get_system_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get system information for RBAC configuration (disciplines, resources, etc.)."""
    disciplines = [
        DisciplineInfo(code=code, display_name=name)
        for code, name in DISCIPLINES.items()
    ]

    resource_types = [
        ResourceTypeInfo(
            code=rt,
            display_name=RESOURCE_DISPLAY_INFO.get(rt, (rt, ""))[0],
            description=RESOURCE_DISPLAY_INFO.get(rt, ("", rt))[1],
        )
        for rt in sorted(RESOURCE_TYPES)
    ]

    return RBACSystemInfo(
        disciplines=disciplines,
        resource_types=resource_types,
        permission_actions=["read", "write", "delete", "approve", "manage"],
    )


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(
    role_data: RoleCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new custom role."""
    # Check if role name already exists
    existing = rbac_service.get_role_by_name(db, role_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role with name '{role_data.name}' already exists",
        )

    # Validate discipline if provided
    if role_data.discipline and role_data.discipline not in DISCIPLINES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid discipline: {role_data.discipline}",
        )

    # Create the role
    role = rbac_service.create_role(
        db,
        name=role_data.name,
        display_name=role_data.display_name,
        description=role_data.description,
        discipline=role_data.discipline,
        color=role_data.color,
        created_by_id=current_user.id,
        is_system=False,
    )

    # Set initial permissions if provided
    if role_data.permissions:
        rbac_service.bulk_set_role_permissions(db, role.id, role_data.permissions)
        # Refresh to get permissions
        db.refresh(role)

    return role


@router.get("/", response_model=list[RoleListItem])
def list_roles(
    include_inactive: bool = False,
    discipline: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all roles with user counts."""
    roles = rbac_service.list_roles(db, include_inactive, discipline)

    # Convert to list items with counts
    result = []
    for role in roles:
        # Count users with this role
        user_count = db.query(rbac_service.UserRole).filter(
            rbac_service.UserRole.role_id == role.id
        ).count()

        result.append(
            RoleListItem(
                id=role.id,
                name=role.name,
                display_name=role.display_name,
                discipline=role.discipline,
                color=role.color,
                is_system=role.is_system,
                is_active=role.is_active,
                permission_count=len(role.permissions),
                user_count=user_count,
            )
        )

    return result


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific role with its permissions."""
    role = rbac_service.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )
    return role


@router.patch("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    role_data: RoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a role's details."""
    try:
        role = rbac_service.update_role(
            db,
            role_id,
            display_name=role_data.display_name,
            description=role_data.description,
            discipline=role_data.discipline,
            color=role_data.color,
            is_active=role_data.is_active,
        )
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found",
            )
        return role
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete a custom role (cannot delete system roles or roles with assigned users)."""
    try:
        deleted = rbac_service.delete_role(db, role_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found",
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{role_id}/permissions", status_code=status.HTTP_201_CREATED)
def set_role_permission(
    role_id: int,
    permission: PermissionSet,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Set a permission for a role on a specific resource."""
    # Verify role exists
    role = rbac_service.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    try:
        perm = rbac_service.set_role_permission(
            db,
            role_id,
            permission.resource_type,
            can_read=permission.can_read,
            can_write=permission.can_write,
            can_delete=permission.can_delete,
            can_approve=permission.can_approve,
            can_manage=permission.can_manage,
            conditions=permission.conditions,
        )
        return perm
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.put("/{role_id}/permissions/bulk")
def bulk_update_permissions(
    role_id: int,
    data: BulkPermissionUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Bulk update permissions for a role."""
    # Verify role exists
    role = rbac_service.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    try:
        permissions = rbac_service.bulk_set_role_permissions(
            db, role_id, data.permissions
        )
        return {"updated_count": len(permissions)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{role_id}/permissions/{resource_type}", status_code=status.HTTP_204_NO_CONTENT)
def remove_role_permission(
    role_id: int,
    resource_type: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove a permission from a role."""
    deleted = rbac_service.remove_role_permission(db, role_id, resource_type)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )


@router.get("/{role_id}/stats", response_model=RoleStats)
def get_role_stats(
    role_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get statistics for a role."""
    role = rbac_service.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    # Count users with this role
    from sqlalchemy import select, func
    from ..rbac_models import UserRole
    from ..models import User as UserModel

    user_count = db.scalar(
        select(func.count(UserRole.id)).where(UserRole.role_id == role_id)
    ) or 0

    active_user_count = db.scalar(
        select(func.count(UserRole.id))
        .join(UserModel, UserModel.id == UserRole.user_id)
        .where(UserRole.role_id == role_id, UserModel.is_active == True)
    ) or 0

    return RoleStats(
        role_id=role.id,
        role_name=role.name,
        display_name=role.display_name,
        user_count=user_count,
        active_user_count=active_user_count,
        permission_count=len(role.permissions),
    )
