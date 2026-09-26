"""Tracker file resolution — always the latest `_DDMMYYYY`-dated file.

The Planner saves dated versions of each tracker in
``E:\\ENGINEERING_DATA\\trackers\\`` (e.g. ``IHP- Construction Projects_07092026.xlsx``
and ``..._15092026.xlsx``). The system must always point at the NEWEST
version, never a hardcoded date. Supported date suffixes: ``_DDMMYYYY``,
``_YYYYMMDD``, and ``_YYYY-MM-DD`` (the DSR files).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_DDMYYYY = re.compile(r"_(\d{2})(\d{2})(\d{4})$")     # _15092026
_YYYYMMDD = re.compile(r"_(\d{4})(\d{2})(\d{2})$")    # _20260916 (unambiguous only)
_ISO = re.compile(r"_(\d{4})-(\d{2})-(\d{2})$")       # _2026-08-27


def _suffix_date(stem: str) -> datetime | None:
    m = _ISO.search(stem)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DDMYYYY.search(stem)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = _YYYYMMDD.search(stem)
            if not (m and 1 <= int(m.group(3)) <= 31):
                return None
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


#: Extensions the trackers are exported in. The Planner saves BOTH an
#: .xlsx (Excel) and a .md (markdown dump) for the same date; the .md is
#: often the only file present for the newest date, so both must be scanned.
DEFAULT_SUFFIXES: tuple[str, ...] = (".xlsx", ".md")


def latest_dated(directory: Path | str, prefix: str,
                 suffix: str | None = None,
                 suffixes: tuple[str, ...] | None = None) -> Path | None:
    """Newest dated file in `directory` whose stem starts with `prefix`.

    By default BOTH ``.xlsx`` and ``.md`` exports are considered and the file
    with the newest ``_DDMMYYYY`` date wins (a stale ``.xlsx`` never shadows a
    newer ``.md``). Pass `suffix` to restrict to one extension, or `suffixes`
    for a custom set.

    Falls back to the only/undated match when no dated version exists.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return None
    allowed = (suffix,) if suffix else (suffixes or DEFAULT_SUFFIXES)
    allowed = tuple(s.lower() for s in allowed)
    # (date, extension priority, path): a lower priority index wins ties so
    # that, for the same date, the .xlsx is preferred over the .md dump.
    candidates: list[tuple[datetime, int, Path]] = []
    undated: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if not path.stem.lower().startswith(prefix.lower()):
            continue
        date = _suffix_date(path.stem)
        if date:
            candidates.append((date, allowed.index(path.suffix.lower()), path))
        else:
            undated.append(path)
    if candidates:
        best = max(candidates, key=lambda t: (t[0], -t[1]))
        return best[2]
    return undated[0] if len(undated) == 1 else None


def _iso_date(path: Path | None) -> str | None:
    """The `_DDMMYYYY` suffix date of a tracker file as ISO, or None."""
    if path is None:
        return None
    d = _suffix_date(path.stem)
    return d.strftime("%Y-%m-%d") if d else None


def tracker_status(trackers_dir: Path | str, pr_request_dir: Path | str) -> dict:
    """What the system currently points at (planner, O&M, PR requests)."""
    planner = latest_dated(trackers_dir, "IHP- Construction Projects")
    om = latest_dated(trackers_dir, "O&M Project Progress Tracking")
    pr_dir = Path(pr_request_dir)
    pr_files = []
    if pr_dir.is_dir():
        for path in sorted(pr_dir.glob("*.pdf"), key=lambda p: p.name.lower()):
            pr_files.append({
                "filename": path.name,
                "size_kb": round(path.stat().st_size / 1024, 1),
            })
    return {
        "trackers_dir": str(trackers_dir),
        "planner_latest": planner.name if planner else None,
        "planner_path": str(planner) if planner else None,
        "planner_date": _iso_date(planner),
        "om_latest": om.name if om else None,
        "om_path": str(om) if om else None,
        "om_date": _iso_date(om),
        "pr_request_dir": str(pr_dir),
        "pr_request_dir_exists": pr_dir.is_dir(),
        "pr_request_pdfs": pr_files,
        "pr_request_count": len(pr_files),
        "note": "the system always resolves the newest _DDMMYYYY-dated file",
    }
