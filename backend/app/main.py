"""FastAPI application factory.

Routers are mounted under /api. CORS is intentionally disabled: the frontend
dev server proxies /api to this backend, and production serves both behind
one origin.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from .api import (  # noqa: F401 (routers registered below)
    access_requests,
    admin,
    ai,
    auth,
    closeout,
    construction,
    construction_crew,
    construction_mto,
    markers,
    reference,
    data_points,
    disposition,
    ear,
    icr,
    imports,
    intake,
    mom,
    projects,
    public,
    roles,
    settings,
    sow_boq,
    mto,
    user_roles,
)
from .core.config import get_settings
from .core.security import hash_password
from .db import Base, SessionLocal, engine
from .models import User
# Import RBAC models to register them with SQLAlchemy metadata
from . import rbac_models  # noqa: F401


def seed_admin_if_empty() -> None:
    """Create the initial admin user when the users table is empty."""
    settings = get_settings()
    db = SessionLocal()
    try:
        if db.scalar(select(User).limit(1)) is None:
            db.add(
                User(
                    username=settings.ADMIN_USERNAME,
                    full_name="Platform Administrator",
                    email="",
                    hashed_password=hash_password(settings.ADMIN_PASSWORD),
                    role="admin",
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()


def seed_builtin_roles() -> None:
    """Make sure Admin -> Roles lists the platform's built-in roles.

    Idempotent: it only inserts roles that are missing, so an admin's edits to a
    system role survive the next restart.
    """
    from .services.rbac_seed import seed_roles

    db = SessionLocal()
    try:
        admin = db.scalar(select(User).order_by(User.id))
        if admin is None:
            return
        summary = seed_roles(db, created_by_id=admin.id)
        if summary["roles_created"]:
            print(f"RBAC: seeded built-in roles {summary['roles_created']}")
    except Exception as exc:  # noqa: BLE001 — never block startup on the catalogue
        print(f"RBAC: role seeding skipped ({exc})")
    finally:
        db.close()


def warn_insecure_defaults() -> None:
    """Log a loud warning when known-insecure default secrets are active.

    Deliberately does not crash the app (dev machines rely on the defaults),
    but operators checking `docker compose logs backend` on a VPS cannot
    miss it.
    """
    import logging

    logger = logging.getLogger("ihp.startup")
    s = get_settings()
    if s.SECRET_KEY == "dev-secret-key-change-me-in-production":
        logger.warning(
            "SECRET_KEY is the built-in default! Anyone can forge auth tokens. "
            "Set SECRET_KEY (openssl rand -hex 32) in .env and restart."
        )
    if s.ADMIN_PASSWORD in ("admin123", "change-me-admin-password", ""):
        logger.warning(
            "ADMIN_PASSWORD is a known default/empty! Change it in .env and "
            "restart, or the seeded admin account is trivially guessable."
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Dev/test convenience: create tables directly. Production deployments
    # manage the schema via Alembic migrations (see backend/alembic/).
    Base.metadata.create_all(bind=engine)
    seed_admin_if_empty()
    seed_builtin_roles()
    warn_insecure_defaults()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="KAUST IHP Project Delivery Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(mom.router, prefix="/api")
    app.include_router(intake.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(disposition.router, prefix="/api")
    app.include_router(ear.router, prefix="/api")
    app.include_router(sow_boq.router, prefix="/api")
    app.include_router(icr.router, prefix="/api")
    app.include_router(construction_mto.router, prefix="/api")
    app.include_router(construction.router, prefix="/api")
    app.include_router(construction.dashboard_router, prefix="/api")
    app.include_router(construction_crew.router, prefix="/api")
    app.include_router(closeout.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(mto.router, prefix="/api")
    app.include_router(reference.router, prefix="/api")
    app.include_router(markers.router, prefix="/api")
    app.include_router(data_points.router, prefix="/api")
    # Public (no auth): the read-only dashboard + the access-request form.
    app.include_router(public.router, prefix="/api")
    # Admin inbox for those requests (users.manage capability).
    app.include_router(access_requests.router, prefix="/api")

    # RBAC routers
    app.include_router(roles.router)
    app.include_router(user_roles.router)
    app.include_router(user_roles.override_router)
    app.include_router(user_roles.permissions_router)
    app.include_router(user_roles.dashboard_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
