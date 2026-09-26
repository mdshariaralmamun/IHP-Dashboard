"""Enhanced RBAC models for flexible role and permission management.

This module extends the basic role system in models.py with:
- Custom role definitions with descriptions
- Granular resource permissions (read/write/delete)
- User-role assignments (many-to-many)
- Permission inheritance and override capabilities
"""

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Permission actions for granular access control
PermissionAction = Literal["read", "write", "delete", "approve", "manage"]

# Resource types in the system
RESOURCE_TYPES = {
    "projects",
    "mom",
    "ear",
    "sow",
    "boq",
    "mto",
    "construction_mto",
    "procurement",
    "work_permit",
    "construction",
    "closeout",
    "icr_handoff",
    "users",
    "roles",
    "attachments",
    "data_points",
    "ai_proposals",
    "master_pricing",
    "reports",
    "audit_logs",
}

# Predefined disciplines/trades for assignment
DISCIPLINES = {
    "civil_arch": "Civil/Architectural Engineer",
    "electrical": "Electrical Engineer",
    "plumbing_gas": "Plumbing/Gas Piping Engineer",
    "hvac": "HVAC Engineer",
    "low_current": "Low Current Engineer",
    "fire_protection": "Fire Protection Engineer",
    "document_control": "Document Controller",
    "safety": "Safety Officer",
    "project_control": "Project Control",
    "procurement": "Procurement Department",
    "construction_manager": "Construction Manager",
    "planner": "Planner",
    "site_supervisor": "Site Supervisor",
    "technician": "Technician",
    "labor": "Labor",
    "qa_qc": "QA/QC Engineer",
    "admin": "Administrator",
}


class Role(Base):
    """Custom role definition with permissions and description.

    Roles can be system-defined (is_system=True) or custom created by admins.
    Each role defines what resources can be accessed and with what actions.
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    # System roles cannot be deleted (admin, planning, etc.)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Associated discipline/trade (nullable for non-trade roles)
    discipline: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Role color for UI display (hex color code)
    color: Mapped[str] = mapped_column(String(7), default="#6B7280")

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    # Relationships
    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        order_by="RolePermission.id",
    )
    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )


class RolePermission(Base):
    """Permission assigned to a role for a specific resource.

    Defines what actions (read/write/delete/approve/manage) a role can perform
    on a specific resource type (projects, mom, ear, etc.).
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "resource_type", name="uq_role_resource"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))

    # Resource type (e.g., "projects", "mom", "ear")
    resource_type: Mapped[str] = mapped_column(String(64), index=True)

    # Actions allowed on this resource
    can_read: Mapped[bool] = mapped_column(Boolean, default=False)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional conditions (JSON):
    # - own_only: bool - can only access own records
    # - trade_scope: list[str] - limit to specific trades
    # - stage_scope: list[str] - limit to specific project stages
    conditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    role: Mapped[Role] = relationship(back_populates="permissions")


class UserRole(Base):
    """Many-to-many relationship between users and roles.

    A user can have multiple roles, and each role can be assigned to multiple users.
    The primary_role flag indicates which role is the user's main role for display.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))

    # Mark if this is the user's primary role for display purposes
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional: role-specific metadata (e.g., date ranges, project scope)
    # Note: renamed from 'metadata' to avoid SQLAlchemy reserved word conflict
    role_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    assigned_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    role: Mapped[Role] = relationship(back_populates="user_roles")


class PermissionOverride(Base):
    """User-specific permission override for fine-grained control.

    Allows granting or revoking specific permissions to individual users
    independent of their roles. Useful for temporary access or exceptions.
    """

    __tablename__ = "permission_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "resource_type", name="uq_user_resource_override"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    resource_type: Mapped[str] = mapped_column(String(64), index=True)

    # Override actions (NULL means inherit from roles)
    can_read: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    can_write: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    can_delete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    can_approve: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    can_manage: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Optional reason for the override
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional expiry date for temporary access
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    granted_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class RoleTemplate(Base):
    """Pre-configured role templates for quick role creation.

    Templates make it easy to create common role configurations without
    manually setting up all permissions each time.
    """

    __tablename__ = "role_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    # Discipline this template is for (nullable for generic templates)
    discipline: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Template permissions structure (same as RolePermission but as JSON)
    # { "resource_type": { "can_read": bool, "can_write": bool, ... } }
    permissions_config: Mapped[dict] = mapped_column(JSON, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
