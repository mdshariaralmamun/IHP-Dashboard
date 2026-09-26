"""Seed the RBAC role catalogue with the platform's built-in roles.

The RBAC migration only creates the schema, so Admin -> Roles opened on an empty
table and (because of the separate trailing-slash bug) never even loaded. This
runs on every startup and is idempotent: a role that already exists is left
exactly as the admin configured it, so renames and re-scoping survive restarts.

Capabilities (the platform's own model, e.g. "sow.manage") are projected onto the
RBAC permission shape (resource_type + can_read/write/delete/approve/manage) so
the role detail screen shows something meaningful. Authorisation itself still
comes from core.rbac.ROLE_DEFAULT_PERMISSIONS.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import ROLE_DEFAULT_PERMISSIONS
from ..models import ROLE_VIEWER
from ..rbac_models import Role, RolePermission

#: name -> (display name, description, colour)
BUILTIN_ROLES: dict[str, tuple[str, str, str]] = {
    "admin": (
        "Administrator",
        "Full control: users, roles, settings, imports and every project stage.",
        "#DC2626",
    ),
    "planning": (
        "Planning Engineer",
        "Owns the Planner tracked data: disposition, EAR, SOW/BOQ, procurement and the traceability engine.",
        "#2563EB",
    ),
    "construction_manager": (
        "Construction Manager",
        "Field execution: work permits, construction progress, materials and closeout.",
        "#EA580C",
    ),
    "trade": (
        "Trade Engineer",
        "Contributes discipline input to the MOM and the EAR, and manages MTO items.",
        "#7C3AED",
    ),
    "team_member": (
        "Team Member",
        "Reads the platform and contributes MOM agenda items.",
        "#059669",
    ),
    ROLE_VIEWER: (
        "Viewer (read-only)",
        "Read-only access to dashboards, the project register and documents.",
        "#6B7280",
    ),
}

#: Resources a read-only role may see (viewer, and the read half of every role).
READ_RESOURCES: tuple[str, ...] = (
    "projects", "mom", "ear", "sow", "boq", "mto", "icr",
    "construction", "closeout", "documents", "dashboard", "ai", "data",
)

_ACTION_FLAGS: dict[str, dict[str, bool]] = {
    # capability suffix -> RBAC action flags
    "create": {"can_write": True},
    "edit": {"can_write": True},
    "upload": {"can_write": True},
    "input": {"can_write": True},
    "accept": {"can_write": True},
    "confirm": {"can_write": True},
    "manage": {"can_write": True, "can_manage": True},
    "delete": {"can_delete": True, "can_write": True},
    "approve": {"can_approve": True, "can_write": True},
}


def _resource_and_flags(capability: str) -> tuple[str, dict[str, bool]]:
    """Split "sow.manage" into the resource and the RBAC action flags."""
    parts = capability.split(".")
    resource = parts[0]
    # "ai.proposal.accept" belongs to the "ai" resource.
    suffix = parts[-1]
    return resource, dict(_ACTION_FLAGS.get(suffix, {"can_write": True}))


def _permission_rows(capabilities: frozenset[str]) -> dict[str, dict[str, bool]]:
    """Merge a role's capabilities into one row per resource (can_read always)."""
    resources: dict[str, dict[str, bool]] = {}
    for capability in capabilities:
        resource, flags = _resource_and_flags(capability)
        row = resources.setdefault(
            resource,
            {
                "can_read": True,
                "can_write": False,
                "can_delete": False,
                "can_approve": False,
                "can_manage": False,
            },
        )
        for flag, value in flags.items():
            row[flag] = row.get(flag, False) or value
    return resources


def seed_roles(db: Session, created_by_id: int) -> dict[str, Any]:
    """Create any missing built-in role and its permission rows."""
    created: list[str] = []
    for name, (display_name, description, color) in BUILTIN_ROLES.items():
        existing = db.scalar(select(Role).where(Role.name == name))
        if existing is not None:
            continue
        role = Role(
            name=name,
            display_name=display_name,
            description=description,
            is_system=True,
            is_active=True,
            color=color,
            created_by_id=created_by_id,
        )
        capabilities = frozenset(ROLE_DEFAULT_PERMISSIONS.get(name, frozenset()))
        rows = _permission_rows(capabilities)
        if not rows:
            # A read-only role still needs can_read on what it may see.
            rows = {
                resource: {
                    "can_read": True,
                    "can_write": False,
                    "can_delete": False,
                    "can_approve": False,
                    "can_manage": False,
                }
                for resource in READ_RESOURCES
            }
        for resource_type, flags in sorted(rows.items()):
            role.permissions.append(
                RolePermission(resource_type=resource_type, **flags)
            )
        db.add(role)
        created.append(name)
    if created:
        db.commit()
    return {"roles_created": created, "total_builtin": len(BUILTIN_ROLES)}
