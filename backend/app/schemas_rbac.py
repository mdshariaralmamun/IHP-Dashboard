"""Pydantic schemas for enhanced RBAC endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ===== Role Schemas =====


class RolePermissionBase(BaseModel):
    """Base schema for role permission."""

    resource_type: str
    can_read: bool = False
    can_write: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_manage: bool = False
    conditions: dict | None = None


class RolePermissionResponse(RolePermissionBase):
    """Response schema for role permission."""

    id: int
    role_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class RoleBase(BaseModel):
    """Base schema for role."""

    name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    discipline: str | None = None
    color: str = "#6B7280"


class RoleCreate(RoleBase):
    """Schema for creating a role."""

    permissions: dict[str, dict] | None = None  # Optional initial permissions


class RoleUpdate(BaseModel):
    """Schema for updating a role."""

    display_name: str | None = None
    description: str | None = None
    discipline: str | None = None
    color: str | None = None
    is_active: bool | None = None


class RoleResponse(RoleBase):
    """Response schema for role."""

    id: int
    is_system: bool
    is_active: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    permissions: list[RolePermissionResponse] = []

    class Config:
        from_attributes = True


class RoleListItem(BaseModel):
    """Simplified role for list responses."""

    id: int
    name: str
    display_name: str
    discipline: str | None
    color: str
    is_system: bool
    is_active: bool
    permission_count: int = 0
    user_count: int = 0

    class Config:
        from_attributes = True


# ===== User-Role Schemas =====


class UserRoleAssign(BaseModel):
    """Schema for assigning a role to a user."""

    user_id: int
    role_id: int
    is_primary: bool = False
    metadata: dict | None = None


class UserRoleResponse(BaseModel):
    """Response schema for user-role assignment."""

    id: int
    user_id: int
    role_id: int
    is_primary: bool
    metadata: dict | None
    assigned_by_id: int
    assigned_at: datetime
    role: RoleListItem

    class Config:
        from_attributes = True


class UserWithRoles(BaseModel):
    """User with their assigned roles."""

    id: int
    username: str
    full_name: str
    title: str
    email: str
    is_active: bool
    roles: list[RoleListItem]
    primary_role: RoleListItem | None

    class Config:
        from_attributes = True


# ===== Permission Override Schemas =====


class PermissionOverrideCreate(BaseModel):
    """Schema for creating a permission override."""

    user_id: int
    resource_type: str
    can_read: bool | None = None
    can_write: bool | None = None
    can_delete: bool | None = None
    can_approve: bool | None = None
    can_manage: bool | None = None
    reason: str | None = None
    expires_at: datetime | None = None


class PermissionOverrideUpdate(BaseModel):
    """Schema for updating a permission override."""

    can_read: bool | None = None
    can_write: bool | None = None
    can_delete: bool | None = None
    can_approve: bool | None = None
    can_manage: bool | None = None
    reason: str | None = None
    expires_at: datetime | None = None


class PermissionOverrideResponse(BaseModel):
    """Response schema for permission override."""

    id: int
    user_id: int
    resource_type: str
    can_read: bool | None
    can_write: bool | None
    can_delete: bool | None
    can_approve: bool | None
    can_manage: bool | None
    reason: str | None
    expires_at: datetime | None
    granted_by_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===== Effective Permissions Schemas =====


class ResourcePermissions(BaseModel):
    """Permissions for a specific resource."""

    can_read: bool
    can_write: bool
    can_delete: bool
    can_approve: bool
    can_manage: bool


class UserPermissionsResponse(BaseModel):
    """All effective permissions for a user."""

    user_id: int
    permissions: dict[str, ResourcePermissions]


class PermissionCheckRequest(BaseModel):
    """Request to check a specific permission."""

    user_id: int
    resource_type: str
    action: Literal["read", "write", "delete", "approve", "manage"]


class PermissionCheckResponse(BaseModel):
    """Response for permission check."""

    has_permission: bool
    resource_type: str
    action: str


# ===== Role Template Schemas =====


class RoleTemplateBase(BaseModel):
    """Base schema for role template."""

    name: str
    display_name: str
    description: str
    discipline: str | None = None
    permissions_config: dict


class RoleTemplateResponse(RoleTemplateBase):
    """Response schema for role template."""

    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CreateRoleFromTemplate(BaseModel):
    """Schema for creating a role from a template."""

    template_id: int
    role_name: str
    display_name: str
    custom_description: str | None = None


# ===== Bulk Operations =====


class BulkRoleAssignment(BaseModel):
    """Bulk assign roles to multiple users."""

    user_ids: list[int]
    role_id: int
    is_primary: bool = False


class BulkPermissionUpdate(BaseModel):
    """Bulk update permissions for a role."""

    role_id: int
    permissions: dict[str, dict]  # {resource_type: {can_read: bool, ...}}


class PermissionSet(BaseModel):
    """Set permissions for a role on a resource."""

    resource_type: str
    can_read: bool = False
    can_write: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_manage: bool = False
    conditions: dict | None = None


# ===== System Info Schemas =====


class DisciplineInfo(BaseModel):
    """Information about a discipline."""

    code: str
    display_name: str


class ResourceTypeInfo(BaseModel):
    """Information about a resource type."""

    code: str
    display_name: str
    description: str


class RBACSystemInfo(BaseModel):
    """System information for RBAC configuration."""

    disciplines: list[DisciplineInfo]
    resource_types: list[ResourceTypeInfo]
    permission_actions: list[str]


# ===== Dashboard/Stats Schemas =====


class RoleStats(BaseModel):
    """Statistics for a role."""

    role_id: int
    role_name: str
    display_name: str
    user_count: int
    active_user_count: int
    permission_count: int


class UserRoleStats(BaseModel):
    """Statistics for user-role assignments."""

    total_users: int
    users_with_roles: int
    users_without_roles: int
    total_role_assignments: int
    avg_roles_per_user: float


class RBACDashboard(BaseModel):
    """Dashboard data for RBAC overview."""

    total_roles: int
    system_roles: int
    custom_roles: int
    active_roles: int
    total_users: int
    role_stats: list[RoleStats]
    user_role_stats: UserRoleStats
