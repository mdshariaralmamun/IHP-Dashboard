"""Seed script to create default roles and role templates for the RBAC system.

This script should be run after the RBAC migration to populate the system with
predefined roles for all disciplines and common role templates.

Usage:
    python -m app.scripts.seed_rbac_roles
"""

from datetime import datetime, timezone
from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.rbac_models import Role, RolePermission, RoleTemplate, DISCIPLINES
from app.services import rbac_service


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_admin_user_id(db) -> int:
    """Get the first admin user for created_by_id."""
    admin = db.scalar(select(User).where(User.role == "admin").limit(1))
    if not admin:
        raise ValueError("No admin user found. Please create an admin user first.")
    return admin.id


def create_system_roles(db, admin_id: int) -> dict[str, Role]:
    """Create system roles for backwards compatibility with existing role field."""
    print("Creating system roles...")

    system_roles = {
        "admin": {
            "display_name": "Administrator",
            "description": "Full system access with all permissions",
            "discipline": "admin",
            "color": "#DC2626",  # Red
            "permissions": {
                # Grant all permissions to admin
                "projects": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "mom": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "ear": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "sow": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "boq": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "mto": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "construction_mto": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "procurement": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "work_permit": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "construction": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "closeout": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "icr_handoff": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "users": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "roles": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "attachments": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "data_points": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "ai_proposals": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "master_pricing": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "reports": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
                "audit_logs": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": True, "can_manage": True},
            }
        },
        "planning": {
            "display_name": "Planning/Planner",
            "description": "Planning team - manages dispositions, EAR, SOW, BOQ, and procurement",
            "discipline": "planner",
            "color": "#2563EB",  # Blue
            "permissions": {
                "projects": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "mom": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "ear": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "sow": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "boq": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "mto": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "procurement": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "data_points": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "ai_proposals": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": False},
                "master_pricing": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "reports": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
        "construction_manager": {
            "display_name": "Construction Manager",
            "description": "Construction management - oversees work permits, construction, and closeout",
            "discipline": "construction_manager",
            "color": "#EA580C",  # Orange
            "permissions": {
                "projects": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "mom": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "construction_mto": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "work_permit": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "construction": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "closeout": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": True},
                "icr_handoff": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "attachments": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "reports": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
        "trade": {
            "display_name": "Trade Engineer (Generic)",
            "description": "Trade discipline engineer - contributes technical input for their discipline",
            "discipline": None,
            "color": "#059669",  # Green
            "permissions": {
                "projects": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "mom": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "ear": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "mto": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "attachments": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "ai_proposals": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
        "team_member": {
            "display_name": "Team Member",
            "description": "General team member with read-only access and meeting participation",
            "discipline": None,
            "color": "#6B7280",  # Gray
            "permissions": {
                "projects": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "mom": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "reports": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
    }

    created_roles = {}

    for role_name, role_data in system_roles.items():
        # Check if role already exists
        existing = rbac_service.get_role_by_name(db, role_name)
        if existing:
            print(f"  ✓ Role '{role_name}' already exists, skipping...")
            created_roles[role_name] = existing
            continue

        # Create role
        role = rbac_service.create_role(
            db,
            name=role_name,
            display_name=role_data["display_name"],
            description=role_data["description"],
            discipline=role_data["discipline"],
            color=role_data["color"],
            created_by_id=admin_id,
            is_system=True,
        )

        # Set permissions
        if "permissions" in role_data:
            rbac_service.bulk_set_role_permissions(db, role.id, role_data["permissions"])

        created_roles[role_name] = role
        print(f"  ✓ Created system role: {role_name}")

    return created_roles


def create_discipline_roles(db, admin_id: int) -> list[Role]:
    """Create roles for each discipline/trade."""
    print("\nCreating discipline-specific roles...")

    # Base permissions for trade disciplines
    trade_permissions = {
        "projects": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
        "mom": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "ear": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "sow": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "boq": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "mto": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "construction_mto": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "attachments": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "ai_proposals": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
        "master_pricing": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
    }

    # Special permissions for specific disciplines
    discipline_configs = {
        "safety": {
            "additional_permissions": {
                "work_permit": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": False},
            }
        },
        "document_control": {
            "additional_permissions": {
                "attachments": {"can_read": True, "can_write": True, "can_delete": True, "can_approve": False, "can_manage": True},
                "reports": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
        "project_control": {
            "additional_permissions": {
                "procurement": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "icr_handoff": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": True},
            }
        },
        "site_supervisor": {
            "additional_permissions": {
                "construction": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "work_permit": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
        "qa_qc": {
            "additional_permissions": {
                "construction": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": False},
                "closeout": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": True, "can_manage": False},
            }
        },
    }

    created_roles = []

    for discipline_code, discipline_name in DISCIPLINES.items():
        # Skip admin, planner, construction_manager as they're system roles
        if discipline_code in ["admin", "planner", "construction_manager"]:
            continue

        role_name = f"{discipline_code}_engineer" if discipline_code not in ["document_control", "safety", "project_control", "site_supervisor", "technician", "labor", "qa_qc"] else discipline_code

        # Check if role already exists
        existing = rbac_service.get_role_by_name(db, role_name)
        if existing:
            print(f"  ✓ Role '{role_name}' already exists, skipping...")
            created_roles.append(existing)
            continue

        # Build permissions
        permissions = trade_permissions.copy()
        if discipline_code in discipline_configs:
            permissions.update(discipline_configs[discipline_code]["additional_permissions"])

        # Create role
        role = rbac_service.create_role(
            db,
            name=role_name,
            display_name=discipline_name,
            description=f"{discipline_name} - responsible for {discipline_code} discipline work",
            discipline=discipline_code,
            color="#059669",  # Green for trade roles
            created_by_id=admin_id,
            is_system=False,
        )

        # Set permissions
        rbac_service.bulk_set_role_permissions(db, role.id, permissions)

        created_roles.append(role)
        print(f"  ✓ Created role: {role_name} ({discipline_name})")

    return created_roles


def create_role_templates(db) -> list[RoleTemplate]:
    """Create role templates for quick role creation."""
    print("\nCreating role templates...")

    templates = [
        {
            "name": "trade_engineer_template",
            "display_name": "Trade Engineer Template",
            "description": "Template for creating trade discipline engineer roles",
            "discipline": None,
            "permissions_config": {
                "projects": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "mom": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "ear": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
                "mto": {"can_read": True, "can_write": True, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
        {
            "name": "readonly_viewer",
            "display_name": "Read-Only Viewer",
            "description": "Template for users who need read-only access to projects and documents",
            "discipline": None,
            "permissions_config": {
                "projects": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "mom": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "ear": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "sow": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
                "reports": {"can_read": True, "can_write": False, "can_delete": False, "can_approve": False, "can_manage": False},
            }
        },
    ]

    created_templates = []

    for template_data in templates:
        # Check if template already exists
        existing = db.scalar(
            select(RoleTemplate).where(RoleTemplate.name == template_data["name"])
        )
        if existing:
            print(f"  ✓ Template '{template_data['name']}' already exists, skipping...")
            created_templates.append(existing)
            continue

        template = RoleTemplate(
            name=template_data["name"],
            display_name=template_data["display_name"],
            description=template_data["description"],
            discipline=template_data["discipline"],
            permissions_config=template_data["permissions_config"],
            is_active=True,
            created_at=utcnow(),
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        created_templates.append(template)
        print(f"  ✓ Created template: {template_data['name']}")

    return created_templates


def main():
    """Main seeding function."""
    print("=" * 60)
    print("RBAC Roles & Templates Seeding Script")
    print("=" * 60)

    db = SessionLocal()
    try:
        admin_id = get_admin_user_id(db)
        print(f"Using admin user ID: {admin_id}\n")

        # Create system roles
        system_roles = create_system_roles(db, admin_id)
        print(f"Created {len(system_roles)} system roles")

        # Create discipline-specific roles
        discipline_roles = create_discipline_roles(db, admin_id)
        print(f"Created {len(discipline_roles)} discipline roles")

        # Create role templates
        templates = create_role_templates(db)
        print(f"Created {len(templates)} role templates")

        print("\n" + "=" * 60)
        print("✓ RBAC seeding completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error during seeding: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
