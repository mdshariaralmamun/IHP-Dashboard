"""Background AI-corpus jobs: archive scan and embedding backfill.

An archive scan walks thousands of documents and embeds every chunk, so it
cannot run inside a request. The job runs in a daemon thread with its own DB
session and publishes progress to DATA_DIR/ai_ingest_status.json, which the
settings UI (and the CLI) can poll.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.config import get_settings
from ..db import SessionLocal
from ..models import User
from . import archive_ingest

_lock = threading.Lock()
_state: dict[str, Any] = {"archive": None, "backfill": None, "attachments": None}
#: Cooperative stop flags: the workers check them between batches/files.
_stop: dict[str, bool] = {
    "archive": False, "backfill": False, "attachments": False,
}


def _should_stop(kind: str):
    return lambda: _stop.get(kind, False)


def stop(kind: str) -> dict[str, Any]:
    """Ask a running job to stop; in-flight work finishes, the rest is skipped."""
    if kind not in _stop:
        raise KeyError(kind)
    _stop[kind] = True
    with _lock:
        job = _state.get(kind) or {}
        job["stopping"] = True
        job["updated_at"] = _now()
        _state[kind] = job
        _persist()
    return {"stopping": True, "kind": kind}


def _status_file() -> Path:
    data_dir = Path(get_settings().DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "ai_ingest_status.json"


def _persist() -> None:
    try:
        _status_file().write_text(
            json.dumps(_state, indent=2, default=str), encoding="utf-8"
        )
    except OSError:
        pass


def read_status() -> dict[str, Any]:
    """Persisted job state (survives a restart); falls back to memory."""
    try:
        if _status_file().exists():
            return json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return dict(_state)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _progress(kind: str):
    def callback(payload: dict[str, Any]) -> None:
        with _lock:
            job = _state.get(kind) or {}
            job.update(payload)
            job["updated_at"] = _now()
            _state[kind] = job
            _persist()
    return callback


def is_running(kind: str) -> bool:
    job = _state.get(kind) or {}
    return bool(job.get("running"))


def _run_archive_scan(path: str, user_id: int, max_files: int, embed: bool) -> None:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise RuntimeError(f"user {user_id} not found")
        summary = archive_ingest.scan_archive(
            Path(path), db, user, max_files=max_files, embed=embed,
            progress=_progress("archive"), should_stop=_should_stop("archive"),
        )
        with _lock:
            job = _state.get("archive") or {}
            job.update({
                "running": False, "finished_at": _now(), "summary": summary,
                "error": None,
            })
            _state["archive"] = job
            _persist()
    except Exception as exc:  # noqa: BLE001 — surfaced to the UI
        with _lock:
            job = _state.get("archive") or {}
            job.update({"running": False, "finished_at": _now(), "error": str(exc)[:400]})
            _state["archive"] = job
            _persist()
    finally:
        db.close()


def _run_attachments(user_id: int, project_id: int | None, limit: int) -> None:
    from . import app_documents

    db = SessionLocal()
    try:
        summary = app_documents.index_attachments(
            db, user_id=user_id, project_id=project_id, limit=limit,
            embed=False, progress=_progress("attachments"),
            should_stop=_should_stop("attachments"),
        )
        with _lock:
            job = _state.get("attachments") or {}
            job.update({
                "running": False, "finished_at": _now(), "summary": summary,
                "error": None,
            })
            _state["attachments"] = job
            _persist()
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job = _state.get("attachments") or {}
            job.update({"running": False, "finished_at": _now(), "error": str(exc)[:400]})
            _state["attachments"] = job
            _persist()
    finally:
        db.close()


def start_attachment_index(
    user_id: int, project_id: int | None = None, limit: int = 5000
) -> dict[str, Any]:
    with _lock:
        if is_running("attachments"):
            return {"started": False, "reason": "an attachment index is already running"}
        _stop["attachments"] = False
        _state["attachments"] = {
            "running": True, "started_at": _now(), "updated_at": _now(),
            "error": None, "stopping": False,
            "scanned": 0, "indexed": 0, "chunks": 0, "skipped": 0, "failed": 0,
        }
        _persist()
    thread = threading.Thread(
        target=_run_attachments, args=(user_id, project_id, limit), daemon=True
    )
    thread.start()
    return {"started": True, "project_id": project_id, "limit": limit}


def _run_backfill(limit: int) -> None:
    db = SessionLocal()
    try:
        summary = archive_ingest.backfill_embeddings(
            db, limit=limit, progress=_progress("backfill"),
            should_stop=_should_stop("backfill"),
        )
        with _lock:
            job = _state.get("backfill") or {}
            job.update({
                "running": False, "finished_at": _now(), "summary": summary, "error": None,
            })
            _state["backfill"] = job
            _persist()
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job = _state.get("backfill") or {}
            job.update({"running": False, "finished_at": _now(), "error": str(exc)[:400]})
            _state["backfill"] = job
            _persist()
    finally:
        db.close()


def start_archive_scan(
    path: str, user_id: int, max_files: int = 5000, embed: bool = True
) -> dict[str, Any]:
    with _lock:
        if is_running("archive"):
            return {"started": False, "reason": "an archive scan is already running"}
        _stop["archive"] = False
        _state["archive"] = {
            "running": True, "path": path, "started_at": _now(),
            "updated_at": _now(), "error": None, "stopping": False,
            "seen": 0, "ingested": 0, "chunks": 0, "embedded": 0, "failed": 0,
        }
        _persist()
    thread = threading.Thread(
        target=_run_archive_scan, args=(path, user_id, max_files, embed), daemon=True
    )
    thread.start()
    return {"started": True, "path": path, "embed": embed, "max_files": max_files}


def start_backfill(limit: int = 5000) -> dict[str, Any]:
    with _lock:
        if is_running("backfill"):
            return {"started": False, "reason": "an embedding backfill is already running"}
        _stop["backfill"] = False
        _state["backfill"] = {
            "running": True, "started_at": _now(), "updated_at": _now(),
            "error": None, "stopping": False,
            "embedded": 0, "scanned": 0, "pending": None,
        }
        _persist()
    thread = threading.Thread(target=_run_backfill, args=(limit,), daemon=True)
    thread.start()
    return {"started": True, "limit": limit}
