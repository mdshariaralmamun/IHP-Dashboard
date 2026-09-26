"""Enhanced RBAC service layer for role and permission management.

Provides functions for:
- Creating and managing custom roles
- Assigning permissions to roles
- Managing user-role assignments
- Checking effective permissions with overrides
- Role templates for quick setup
"""

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select, delete, and_, or_
from sqlalchemy.orm import Session, selectinload

from ..models import User
from ..rbac_models import (
    Role,
    RolePermission,
    UserRole,
    PermissionOverride,
    RoleTemplate,
    RESOURCE_TYPES,
    DISCIPLINES,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ===== Role Management =====


def create_role(
    db: Session,
    name: str,
    display_name: str,
    description: str,
    discipline: str | None,
    color: str,
    created_by_id: int,
    is_system: bool = False,
) -> Role:
    """Create a new role."""
    role = Role(
        name=name,
        display_name=display_name,
        description=description,
        discipline=discipline,
        color=color,
        is_system=is_system,
        created_by_id=created_by_id,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def get_role(db: Session, role_id: int) -> Role | None:
    """Get a role by ID with its permissions loaded."""
    return db.scalar(
        select(Role)
        .where(Role.id == role_id)
        .options(selectinload(Role.permissions))
    )


def get_role_by_name(db: Session, name: str) -> Role | None:
    """Get a role by name with its permissions loaded."""
    return db.scalar(
        select(Role)
        .where(Role.name == name)
        .options(selectinload(Role.permissions))
    )


def list_roles(
    db: Session,
    include_inactive: bool = False,
    discipline_filter: str | None = None,
) -> list[Role]:
    """List all roles with optional filters."""
    stmt = select(Role).options(selectinload(Role.permissions))

    if not include_inactive:
        stmt = stmt.where(Role.is_active == True)

    if discipline_filter:
        stmt = stmt.where(Role.discipline == discipline_filter)

    stmt = stmt.order_by(Role.name)
    return list(db.scalars(stmt).all())


def update_role(
    db: Session,
    role_id: int,
    display_name: str | None = None,
    description: str | None = None,
    discipline: str | None = None,
    color: str | None = None,
    is_active: bool | None = None,
) -> Role | None:
    """Update role details."""
    role = get_role(db, role_id)
    if not role:
        return None

    if role.is_system and is_active is False:
        raise ValueError("Cannot deactivate system roles")

    if display_name is not None:
        role.display_name = display_name
    if description is not None:
        role.description = description
    if discipline is not None:
        role.discipline = discipline
    if color is not None:
        role.color = color
    if is_active is not None:
        role.is_active = is_active

    db.commit()
    db.refresh(role)
    return role


def delete_role(db: Session, role_id: int) -> bool:
    """Delete a role (only if not system role and no users assigned)."""
    role = get_role(db, role_id)
    if not role:
        return False

    if role.is_system:
        raise ValueError("Cannot delete system roles")

    # Check if any users have this role
    user_count = db.scalar(
        select(UserRole).where(UserRole.role_id == role_id).limit(1)
    )
    if user_count:
        raise ValueError("Cannot delete role with assigned users")

    db.delete(role)
    db.commit()
    return True


# ===== Permission Management =====


def set_role_permission(
    db: Session,
    role_id: int,
    resource_type: str,
    can_read: bool = False,
    can_write: bool = False,
    can_delete: bool = False,
    can_approve: bool = False,
    can_manage: bool = False,
    conditions: dict | None = None,
) -> RolePermission:
    """Set or update permission for a role on a resource."""
    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"Invalid resource_type: {resource_type}")

    # Get or create permission
    perm = db.scalar(
        select(RolePermission).where(
            and_(
                RolePermission.role_id == role_id,
                RolePermission.resource_type == resource_type,
            )
        )
    )

    if not perm:
        perm = RolePermission(role_id=role_id, resource_type=resource_type)
        db.add(perm)

    perm.can_read = can_read
    perm.can_write = can_write
    perm.can_delete = can_delete
    perm.can_approve = can_approve
    perm.can_manage = can_manage
    perm.conditions = conditions

    db.commit()
    db.refresh(perm)
    return perm


def bulk_set_role_permissions(
    db: Session,
    role_id: int,
    permissions: dict[str, dict],
) -> list[RolePermission]:
    """Set multiple permissions for a role at once.

    Args:
        permissions: {
            "resource_type": {
                "can_read": bool, "can_write": bool, ...
            }
        }
    """
    results = []
    for resource_type, perms in permissions.items():
        perm = set_role_permission(
            db,
            role_id,
            resource_type,
            can_read=perms.get("can_read", False),
            can_write=perms.get("can_write", False),
            can_delete=perms.get("can_delete", False),
            can_approve=perms.get("can_approve", False),
            can_manage=perms.get("can_manage", False),
            conditions=perms.get("conditions"),
        )
        results.append(perm)

    return results


def remove_role_permission(
    db: Session,
    role_id: int,
    resource_type: str,
) -> bool:
    """Remove a permission from a role."""
    result = db.execute(
        delete(RolePermission).where(
            and_(
                RolePermission.role_id == role_id,
                RolePermission.resource_type == resource_type,
            )
        )
    )
    db.commit()
    return result.rowcount > 0


def get_role_permissions(db: Session, role_id: int) -> list[RolePermission]:
    """Get all permissions for a role."""
    return list(
        db.scalars(
            select(RolePermission)
            .where(RolePermission.role_id == role_id)
            .order_by(RolePermission.resource_type)
        ).all()
    )


# ===== User-Role Assignment =====


def assign_role_to_user(
    db: Session,
    user_id: int,
    role_id: int,
    assigned_by_id: int,
    is_primary: bool = False,
    metadata: dict | None = None,
) -> UserRole:
    """Assign a role to a user."""
    # Check if already assigned
    existing = db.scalar(
        select(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
    )

    if existing:
        # Update existing assignment
        existing.is_primary = is_primary
        existing.role_metadata = metadata
        existing.assigned_by_id = assigned_by_id
        existing.assigned_at = utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    # If setting as primary, unset other primary roles
    if is_primary:
        db.execute(
            UserRole.__table__.update()
            .where(UserRole.user_id == user_id)
            .values(is_primary=False)
        )

    user_role = UserRole(
        user_id=user_id,
        role_id=role_id,
        is_primary=is_primary,
        role_metadata=metadata,
        assigned_by_id=assigned_by_id,
    )
    db.add(user_role)
    db.commit()
    db.refresh(user_role)
    return user_role


def remove_role_from_user(
    db: Session,
    user_id: int,
    role_id: int,
) -> bool:
    """Remove a role from a user."""
    result = db.execute(
        delete(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
    )
    db.commit()
    return result.rowcount > 0


def get_user_roles(db: Session, user_id: int) -> list[Role]:
    """Get all roles assigned to a user."""
    user_roles = db.scalars(
        select(UserRole)
        .where(UserRole.user_id == user_id)
        .options(selectinload(UserRole.role).selectinload(Role.permissions))
    ).all()

    return [ur.role for ur in user_roles if ur.role.is_active]


def get_primary_role(db: Session, user_id: int) -> Role | None:
    """Get the user's primary role."""
    user_role = db.scalar(
        select(UserRole)
        .where(
            and_(
                UserRole.user_id == user_id,
                UserRole.is_primary == True,
            )
        )
        .options(selectinload(UserRole.role))
    )

    return user_role.role if user_role else None


def set_primary_role(db: Session, user_id: int, role_id: int) -> bool:
    """Set a role as the user's primary role."""
    # Verify user has this role
    user_role = db.scalar(
        select(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
    )

    if not user_role:
        return False

    # Unset all primary flags for this user
    db.execute(
        UserRole.__table__.update()
        .where(UserRole.user_id == user_id)
        .values(is_primary=False)
    )

    # Set the new primary
    user_role.is_primary = True
    db.commit()
    return True


# ===== Permission Overrides =====


def set_permission_override(
    db: Session,
    user_id: int,
    resource_type: str,
    granted_by_id: int,
    can_read: bool | None = None,
    can_write: bool | None = None,
    can_delete: bool | None = None,
    can_approve: bool | None = None,
    can_manage: bool | None = None,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> PermissionOverride:
    """Set a permission override for a user."""
    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"Invalid resource_type: {resource_type}")

    # Get or create override
    override = db.scalar(
        select(PermissionOverride).where(
            and_(
                PermissionOverride.user_id == user_id,
                PermissionOverride.resource_type == resource_type,
            )
        )
    )

    if not override:
        override = PermissionOverride(
            user_id=user_id,
            resource_type=resource_type,
            granted_by_id=granted_by_id,
        )
        db.add(override)

    override.can_read = can_read
    override.can_write = can_write
    override.can_delete = can_delete
    override.can_approve = can_approve
    override.can_manage = can_manage
    override.reason = reason
    override.expires_at = expires_at
    override.granted_by_id = granted_by_id

    db.commit()
    db.refresh(override)
    return override


def remove_permission_override(
    db: Session,
    user_id: int,
    resource_type: str,
) -> bool:
    """Remove a permission override."""
    result = db.execute(
        delete(PermissionOverride).where(
            and_(
                PermissionOverride.user_id == user_id,
                PermissionOverride.resource_type == resource_type,
            )
        )
    )
    db.commit()
    return result.rowcount > 0


def get_user_overrides(db: Session, user_id: int) -> list[PermissionOverride]:
    """Get all permission overrides for a user."""
    return list(
        db.scalars(
            select(PermissionOverride)
            .where(PermissionOverride.user_id == user_id)
            .order_by(PermissionOverride.resource_type)
        ).all()
    )


# ===== Effective Permissions Calculation =====


def get_effective_permissions(
    db: Session,
    user_id: int,
    resource_type: str,
) -> dict[str, bool]:
    """Calculate effective permissions for a user on a resource.

    Priority:
    1. Active permission overrides (if not expired)
    2. Union of all role permissions
    3. Default: all False

    Returns:
        {
            "can_read": bool,
            "can_write": bool,
            "can_delete": bool,
            "can_approve": bool,
            "can_manage": bool,
        }
    """
    now = utcnow()

    # Start with defaults
    effective = {
        "can_read": False,
        "can_write": False,
        "can_delete": False,
        "can_approve": False,
        "can_manage": False,
    }

    # Check for permission override first
    override = db.scalar(
        select(PermissionOverride).where(
            and_(
                PermissionOverride.user_id == user_id,
                PermissionOverride.resource_type == resource_type,
                or_(
                    PermissionOverride.expires_at.is_(None),
                    PermissionOverride.expires_at > now,
                ),
            )
        )
    )

    if override:
        # Apply override (None means inherit from roles)
        if override.can_read is not None:
            effective["can_read"] = override.can_read
        if override.can_write is not None:
            effective["can_write"] = override.can_write
        if override.can_delete is not None:
            effective["can_delete"] = override.can_delete
        if override.can_approve is not None:
            effective["can_approve"] = override.can_approve
        if override.can_manage is not None:
            effective["can_manage"] = override.can_manage

        # If all overrides are set, return early
        if all(
            getattr(override, f"can_{action}") is not None
            for action in ["read", "write", "delete", "approve", "manage"]
        ):
            return effective

    # Get permissions from all user's active roles (union)
    user_roles = db.scalars(
        select(UserRole)
        .where(UserRole.user_id == user_id)
        .options(
            selectinload(UserRole.role)
            .selectinload(Role.permissions)
        )
    ).all()

    for user_role in user_roles:
        if not user_role.role.is_active:
            continue

        for perm in user_role.role.permissions:
            if perm.resource_type == resource_type:
                # Union: if any role grants permission, user has it
                effective["can_read"] = effective["can_read"] or perm.can_read
                effective["can_write"] = effective["can_write"] or perm.can_write
                effective["can_delete"] = effective["can_delete"] or perm.can_delete
                effective["can_approve"] = effective["can_approve"] or perm.can_approve
                effective["can_manage"] = effective["can_manage"] or perm.can_manage

    return effective


def has_permission(
    db: Session,
    user_id: int,
    resource_type: str,
    action: Literal["read", "write", "delete", "approve", "manage"],
) -> bool:
    """Check if a user has a specific permission on a resource."""
    perms = get_effective_permissions(db, user_id, resource_type)
    return perms.get(f"can_{action}", False)


def get_all_user_permissions(
    db: Session,
    user_id: int,
) -> dict[str, dict[str, bool]]:
    """Get effective permissions for all resources for a user.

    Returns:
        {
            "resource_type": {
                "can_read": bool,
                "can_write": bool,
                ...
            }
        }
    """
    result = {}
    for resource_type in RESOURCE_TYPES:
        result[resource_type] = get_effective_permissions(db, user_id, resource_type)

    return result


# ===== Role Templates =====


def create_role_from_template(
    db: Session,
    template_id: int,
    role_name: str,
    display_name: str,
    created_by_id: int,
    custom_description: str | None = None,
) -> Role:
    """Create a new role from a template."""
    template = db.scalar(
        select(RoleTemplate).where(RoleTemplate.id == template_id)
    )

    if not template:
        raise ValueError("Template not found")

    if not template.is_active:
        raise ValueError("Template is not active")

    # Create the role
    role = create_role(
        db,
        name=role_name,
        display_name=display_name,
        description=custom_description or template.description,
        discipline=template.discipline,
        color="#6B7280",  # Default color
        created_by_id=created_by_id,
    )

    # Apply template permissions
    bulk_set_role_permissions(db, role.id, template.permissions_config)

    return role


def list_role_templates(
    db: Session,
    include_inactive: bool = False,
    discipline_filter: str | None = None,
) -> list[RoleTemplate]:
    """List available role templates."""
    stmt = select(RoleTemplate)

    if not include_inactive:
        stmt = stmt.where(RoleTemplate.is_active == True)

    if discipline_filter:
        stmt = stmt.where(RoleTemplate.discipline == discipline_filter)

    stmt = stmt.order_by(RoleTemplate.name)
    return list(db.scalars(stmt).all())
