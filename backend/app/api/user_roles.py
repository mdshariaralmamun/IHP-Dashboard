"""API endpoints for user-role assignments and permission management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from ..core.rbac import require_admin, get_current_user
from ..db import get_db
from ..models import User
from ..rbac_models import UserRole as UserRoleModel, Role
from ..schemas_rbac import (
    UserRoleAssign,
    UserRoleResponse,
    UserWithRoles,
    RoleListItem,
    BulkRoleAssignment,
    PermissionOverrideCreate,
    PermissionOverrideUpdate,
    PermissionOverrideResponse,
    UserPermissionsResponse,
    ResourcePermissions,
    PermissionCheckRequest,
    PermissionCheckResponse,
    UserRoleStats,
    RBACDashboard,
    RoleStats,
)
from ..services import rbac_service

router = APIRouter(prefix="/api/user-roles", tags=["user-roles"])


@router.post("/assign", response_model=UserRoleResponse, status_code=status.HTTP_201_CREATED)
def assign_role_to_user(
    assignment: UserRoleAssign,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Assign a role to a user."""
    # Verify user exists
    user = db.scalar(select(User).where(User.id == assignment.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Verify role exists
    role = rbac_service.get_role(db, assignment.role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    user_role = rbac_service.assign_role_to_user(
        db,
        user_id=assignment.user_id,
        role_id=assignment.role_id,
        assigned_by_id=current_user.id,
        is_primary=assignment.is_primary,
        metadata=assignment.metadata,
    )

    # Load role for response
    db.refresh(user_role)
    return user_role


@router.delete("/unassign/{user_id}/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_role_from_user(
    user_id: int,
    role_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove a role from a user."""
    deleted = rbac_service.remove_role_from_user(db, user_id, role_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User-role assignment not found",
        )


@router.get("/user/{user_id}", response_model=UserWithRoles)
def get_user_with_roles(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a user with all their assigned roles."""
    # Only admins can view other users' roles
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other users' roles",
        )

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    roles = rbac_service.get_user_roles(db, user_id)
    primary_role = rbac_service.get_primary_role(db, user_id)

    # Convert to list items
    role_items = []
    for role in roles:
        user_count = db.scalar(
            select(func.count(UserRoleModel.id)).where(UserRoleModel.role_id == role.id)
        ) or 0

        role_items.append(
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

    primary_role_item = None
    if primary_role:
        user_count = db.scalar(
            select(func.count(UserRoleModel.id)).where(UserRoleModel.role_id == primary_role.id)
        ) or 0
        primary_role_item = RoleListItem(
            id=primary_role.id,
            name=primary_role.name,
            display_name=primary_role.display_name,
            discipline=primary_role.discipline,
            color=primary_role.color,
            is_system=primary_role.is_system,
            is_active=primary_role.is_active,
            permission_count=len(primary_role.permissions),
            user_count=user_count,
        )

    return UserWithRoles(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        title=user.title,
        email=user.email,
        is_active=user.is_active,
        roles=role_items,
        primary_role=primary_role_item,
    )


@router.post("/user/{user_id}/primary-role/{role_id}")
def set_user_primary_role(
    user_id: int,
    role_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Set a user's primary role."""
    success = rbac_service.set_primary_role(db, user_id, role_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have this role assigned",
        )
    return {"message": "Primary role updated"}


@router.post("/bulk-assign", status_code=status.HTTP_201_CREATED)
def bulk_assign_roles(
    assignment: BulkRoleAssignment,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Assign a role to multiple users at once."""
    # Verify role exists
    role = rbac_service.get_role(db, assignment.role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    assigned_count = 0
    errors = []

    for user_id in assignment.user_ids:
        try:
            # Verify user exists
            user = db.scalar(select(User).where(User.id == user_id))
            if not user:
                errors.append(f"User {user_id} not found")
                continue

            rbac_service.assign_role_to_user(
                db,
                user_id=user_id,
                role_id=assignment.role_id,
                assigned_by_id=current_user.id,
                is_primary=assignment.is_primary,
            )
            assigned_count += 1
        except Exception as e:
            errors.append(f"User {user_id}: {str(e)}")

    return {
        "assigned_count": assigned_count,
        "total_requested": len(assignment.user_ids),
        "errors": errors,
    }


@router.get("/role/{role_id}/users", response_model=list[UserWithRoles])
def get_role_users(
    role_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get all users assigned to a specific role."""
    role = rbac_service.get_role(db, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found",
        )

    # Get all user-role assignments for this role
    user_roles = db.scalars(
        select(UserRoleModel)
        .where(UserRoleModel.role_id == role_id)
        .options(selectinload(UserRoleModel.role))
    ).all()

    result = []
    for ur in user_roles:
        user = db.scalar(select(User).where(User.id == ur.user_id))
        if not user:
            continue

        roles = rbac_service.get_user_roles(db, user.id)
        primary_role = rbac_service.get_primary_role(db, user.id)

        role_items = []
        for r in roles:
            user_count = db.scalar(
                select(func.count(UserRoleModel.id)).where(UserRoleModel.role_id == r.id)
            ) or 0

            role_items.append(
                RoleListItem(
                    id=r.id,
                    name=r.name,
                    display_name=r.display_name,
                    discipline=r.discipline,
                    color=r.color,
                    is_system=r.is_system,
                    is_active=r.is_active,
                    permission_count=len(r.permissions),
                    user_count=user_count,
                )
            )

        primary_role_item = None
        if primary_role:
            user_count = db.scalar(
                select(func.count(UserRoleModel.id)).where(UserRoleModel.role_id == primary_role.id)
            ) or 0
            primary_role_item = RoleListItem(
                id=primary_role.id,
                name=primary_role.name,
                display_name=primary_role.display_name,
                discipline=primary_role.discipline,
                color=primary_role.color,
                is_system=primary_role.is_system,
                is_active=primary_role.is_active,
                permission_count=len(primary_role.permissions),
                user_count=user_count,
            )

        result.append(
            UserWithRoles(
                id=user.id,
                username=user.username,
                full_name=user.full_name,
                title=user.title,
                email=user.email,
                is_active=user.is_active,
                roles=role_items,
                primary_role=primary_role_item,
            )
        )

    return result


# ===== Permission Overrides =====

override_router = APIRouter(prefix="/api/permission-overrides", tags=["permission-overrides"])


@override_router.post("/", response_model=PermissionOverrideResponse, status_code=status.HTTP_201_CREATED)
def create_permission_override(
    override: PermissionOverrideCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create or update a permission override for a user."""
    # Verify user exists
    user = db.scalar(select(User).where(User.id == override.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    try:
        perm_override = rbac_service.set_permission_override(
            db,
            user_id=override.user_id,
            resource_type=override.resource_type,
            granted_by_id=current_user.id,
            can_read=override.can_read,
            can_write=override.can_write,
            can_delete=override.can_delete,
            can_approve=override.can_approve,
            can_manage=override.can_manage,
            reason=override.reason,
            expires_at=override.expires_at,
        )
        return perm_override
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@override_router.get("/user/{user_id}", response_model=list[PermissionOverrideResponse])
def get_user_overrides(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get all permission overrides for a user."""
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return rbac_service.get_user_overrides(db, user_id)


@override_router.delete("/{user_id}/{resource_type}", status_code=status.HTTP_204_NO_CONTENT)
def remove_permission_override(
    user_id: int,
    resource_type: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove a permission override."""
    deleted = rbac_service.remove_permission_override(db, user_id, resource_type)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission override not found",
        )


# ===== Effective Permissions =====

permissions_router = APIRouter(prefix="/api/permissions", tags=["permissions"])


@permissions_router.get("/user/{user_id}", response_model=UserPermissionsResponse)
def get_user_permissions(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all effective permissions for a user."""
    # Only admins can view other users' permissions
    if current_user.id != user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other users' permissions",
        )

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    all_permissions = rbac_service.get_all_user_permissions(db, user_id)

    # Convert to ResourcePermissions objects
    permissions = {
        resource: ResourcePermissions(**perms)
        for resource, perms in all_permissions.items()
    }

    return UserPermissionsResponse(
        user_id=user_id,
        permissions=permissions,
    )


@permissions_router.post("/check", response_model=PermissionCheckResponse)
def check_permission(
    check: PermissionCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if a user has a specific permission."""
    # Only admins can check other users' permissions
    if current_user.id != check.user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot check other users' permissions",
        )

    has_perm = rbac_service.has_permission(
        db, check.user_id, check.resource_type, check.action
    )

    return PermissionCheckResponse(
        has_permission=has_perm,
        resource_type=check.resource_type,
        action=check.action,
    )


# ===== Dashboard & Statistics =====

dashboard_router = APIRouter(prefix="/api/rbac", tags=["rbac-dashboard"])


@dashboard_router.get("/dashboard", response_model=RBACDashboard)
def get_rbac_dashboard(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get RBAC dashboard with statistics."""
    # Role counts
    total_roles = db.scalar(select(func.count(Role.id))) or 0
    system_roles = db.scalar(
        select(func.count(Role.id)).where(Role.is_system == True)
    ) or 0
    custom_roles = total_roles - system_roles
    active_roles = db.scalar(
        select(func.count(Role.id)).where(Role.is_active == True)
    ) or 0

    # User counts
    total_users = db.scalar(select(func.count(User.id))) or 0

    # Role stats
    roles = rbac_service.list_roles(db, include_inactive=True)
    role_stats = []

    for role in roles:
        user_count = db.scalar(
            select(func.count(UserRoleModel.id)).where(UserRoleModel.role_id == role.id)
        ) or 0

        active_user_count = db.scalar(
            select(func.count(UserRoleModel.id))
            .join(User, User.id == UserRoleModel.user_id)
            .where(UserRoleModel.role_id == role.id, User.is_active == True)
        ) or 0

        role_stats.append(
            RoleStats(
                role_id=role.id,
                role_name=role.name,
                display_name=role.display_name,
                user_count=user_count,
                active_user_count=active_user_count,
                permission_count=len(role.permissions),
            )
        )

    # User-role stats
    total_role_assignments = db.scalar(select(func.count(UserRoleModel.id))) or 0
    users_with_roles = db.scalar(
        select(func.count(func.distinct(UserRoleModel.user_id)))
    ) or 0
    users_without_roles = total_users - users_with_roles
    avg_roles = total_role_assignments / total_users if total_users > 0 else 0

    user_role_stats = UserRoleStats(
        total_users=total_users,
        users_with_roles=users_with_roles,
        users_without_roles=users_without_roles,
        total_role_assignments=total_role_assignments,
        avg_roles_per_user=round(avg_roles, 2),
    )

    return RBACDashboard(
        total_roles=total_roles,
        system_roles=system_roles,
        custom_roles=custom_roles,
        active_roles=active_roles,
        total_users=total_users,
        role_stats=role_stats,
        user_role_stats=user_role_stats,
    )
