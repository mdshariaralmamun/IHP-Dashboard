"""The folders the app reads tracker files from, in priority order.

Two locations are searched for every tracker:

1. **the upload store** — `<DATA_DIR>/trackers`, where
   `/api/admin/import/*` publishes whatever an admin uploads. It lives on
   the persisted data volume, so an upload survives a container rebuild or
   redeploy (the old `backend/data/imports` path did not: it sat in the
   image layer and every rebuild threw the upload away).
2. **the drop folder** — `TRACKERS_DIR` (env default, admin-overridable),
   where the Planner saves its dated exports (a read-only bind mount in
   production).

Resolution is always by the NEWEST `_DDMMYYYY` date across both, so
uploading a newer export immediately makes it the version the whole app
reads — the register, the consistency check, the O&M active-PR list, the
Project Summary / SOW / MOM context and the dashboard's "Auto-tracked
source" banner all go through `status()` / `om_path()` / `planner_path()`
here. The upload store is listed first so it also wins a date tie.

Before this module existed the four O&M lookups in `api/projects.py` and
`api/mom.py` read `settings.TRACKERS_DIR` directly, bypassing the admin
override — in production that is the Windows default path, so those
lookups silently returned nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import get_settings
from . import runtime_settings, tracker_files

#: Filename prefixes the Planner uses for each tracker export.
PLANNER_PREFIX = "IHP- Construction Projects"
OM_PREFIX = "O&M Project Progress Tracking"


def upload_dir() -> Path:
    """Persistent store for tracker files uploaded through the admin UI."""
    return Path(get_settings().DATA_DIR) / "trackers"


def configured_dir() -> Path:
    """The Planner's drop folder: env default with the admin override on top."""
    overrides = runtime_settings.read_overrides()
    return Path(overrides.get("TRACKERS_DIR") or get_settings().TRACKERS_DIR)


def pr_request_dir() -> Path:
    """Where the PR-request PDF copies are dropped (override wins)."""
    overrides = runtime_settings.read_overrides()
    return Path(overrides.get("PR_REQUEST_DIR") or get_settings().PR_REQUEST_DIR)


def search_dirs() -> list[Path]:
    """Folders to search, most-preferred first (upload store, drop folder)."""
    dirs: list[Path] = []
    for candidate in (upload_dir(), configured_dir()):
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def latest(prefix: str) -> Path | None:
    """Newest dated file for `prefix` across every searched folder."""
    path, _dir = tracker_files.latest_dated_many(search_dirs(), prefix)
    return path


def planner_path() -> Path | None:
    """The Planner export the app is currently reading (or None)."""
    return latest(PLANNER_PREFIX)


def om_path() -> Path | None:
    """The O&M export the app is currently reading (or None)."""
    return latest(OM_PREFIX)


def source_of(path: Path | str | None) -> str | None:
    """`"upload"` when a resolved file came from the upload store, else
    `"folder"` — so the UI can show WHERE the live version came from."""
    if not path:
        return None
    parent = Path(path).parent
    return "upload" if parent == upload_dir() else "folder"


def status() -> dict[str, Any]:
    """`tracker_files.tracker_status` over every searched folder.

    Adds `upload_dir`, `configured_dir` and the per-file `*_source` keys
    (`"upload"` / `"folder"`) the upload page and dashboard display.
    """
    data = tracker_files.tracker_status(search_dirs(), pr_request_dir())
    data["upload_dir"] = str(upload_dir())
    data["configured_dir"] = str(configured_dir())
    data["planner_source"] = source_of(data.get("planner_path"))
    data["om_source"] = source_of(data.get("om_path"))
    return data
