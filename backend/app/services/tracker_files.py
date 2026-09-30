"""Tracker file resolution — always the latest `_DDMMYYYY`-dated file.

The Planner saves dated versions of each tracker in
``E:\\ENGINEERING_DATA\\trackers\\`` (e.g. ``IHP- Construction Projects_07092026.xlsx``
and ``..._15092026.xlsx``). The system must always point at the NEWEST
version, never a hardcoded date. Supported date suffixes: ``_DDMMYYYY``,
``_YYYYMMDD``, and ``_YYYY-MM-DD`` (the DSR files).

This module is pure path logic — it knows nothing about settings. The
folders the app actually searches (its own upload store plus the Planner's
drop folder) live in `services.tracker_sources`; `latest_dated_many()`
here resolves the newest file across however many folders it is given.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_DDMYYYY = re.compile(r"_(\d{2})(\d{2})(\d{4})$")     # _15092026
_YYYYMMDD = re.compile(r"_(\d{4})(\d{2})(\d{2})$")    # _20260916 (unambiguous only)
_ISO = re.compile(r"_(\d{4})-(\d{2})-(\d{2})$")       # _2026-08-27


def suffix_date(stem: str) -> datetime | None:
    """The date encoded in a tracker filename's stem, or None.

    Recognises the Planner's `_DDMMYYYY`, its unambiguous `_YYYYMMDD`, and
    the DSR exports' `_YYYY-MM-DD`. Public because an upload that arrives
    under a different name still needs its own date preserved.
    """
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


#: Backwards-compatible alias: scripts/import_planner.py imports this name.
_suffix_date = suffix_date


#: Extensions the trackers are exported in. The Planner saves BOTH an
#: .xlsx (Excel) and a .md (markdown dump) for the same date; the .md is
#: often the only file present for the newest date, so both must be scanned.
DEFAULT_SUFFIXES: tuple[str, ...] = (".xlsx", ".md")


def _candidates(
    directory: Path | str, prefix: str, allowed: tuple[str, ...],
) -> tuple[list[tuple[datetime, int, Path]], list[Path]]:
    """(dated, undated) matches for `prefix` inside one directory.

    Dated entries carry the file's `_DDMMYYYY` date and the extension's
    index in `allowed`; a lower index is preferred when two files share a
    date, so the .xlsx beats the .md dump.
    """
    dated: list[tuple[datetime, int, Path]] = []
    undated: list[Path] = []
    folder = Path(directory)
    if not folder.is_dir():
        return dated, undated
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        if not path.stem.lower().startswith(prefix.lower()):
            continue
        date = suffix_date(path.stem)
        if date:
            dated.append((date, allowed.index(path.suffix.lower()), path))
        else:
            undated.append(path)
    return dated, undated


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
    allowed = (suffix,) if suffix else (suffixes or DEFAULT_SUFFIXES)
    allowed = tuple(s.lower() for s in allowed)
    candidates, undated = _candidates(directory, prefix, allowed)
    if candidates:
        best = max(candidates, key=lambda t: (t[0], -t[1]))
        return best[2]
    return undated[0] if len(undated) == 1 else None


def latest_dated_many(
    directories: "list[Path | str] | tuple[Path | str, ...]",
    prefix: str,
    suffixes: tuple[str, ...] | None = None,
) -> tuple[Path | None, Path | None]:
    """Newest dated match across several folders: `(path, folder)`.

    Folders are searched in the order given and a NEWER date always wins,
    whichever folder it sits in. When two files carry the same date the
    earlier folder wins, which is what lets an admin upload (its store is
    listed first) immediately shadow a stale export in the drop folder.

    Only the newest dated file is ever returned; undated files are a
    last-resort fallback used when no dated version exists anywhere.
    """
    allowed = tuple(s.lower() for s in (suffixes or DEFAULT_SUFFIXES))
    best: tuple[tuple[datetime, int, int], Path, Path] | None = None
    fallback: tuple[Path, Path] | None = None
    for index, directory in enumerate(directories):
        dated, undated = _candidates(directory, prefix, allowed)
        for date, ext_index, path in dated:
            key = (date, -index, -ext_index)
            if best is None or key > best[0]:
                best = (key, path, Path(directory))
        if fallback is None and len(undated) == 1:
            fallback = (undated[0], Path(directory))
    if best is not None:
        return best[1], best[2]
    return fallback if fallback is not None else (None, None)


def ensure_dated(filename: str, when: datetime | None = None) -> str:
    """`filename` guaranteed to end in a `_DDMMYYYY` suffix.

    Planner exports already carry the suffix; an upload that does not would
    always lose to a dated file in the folder, so an undated name is stamped
    with `when` (default: now). Slashes in a client-supplied name are
    flattened so an upload can never escape the store directory.
    """
    safe = Path(filename.replace("\\", "/")).name.strip() or "upload.xlsx"
    path = Path(safe)
    if suffix_date(path.stem):
        return path.name
    stamp = (when or datetime.now()).strftime("%d%m%Y")
    return f"{path.stem}_{stamp}{path.suffix}"


def _iso_date(path: Path | None) -> str | None:
    """The `_DDMMYYYY` suffix date of a tracker file as ISO, or None."""
    if path is None:
        return None
    d = suffix_date(path.stem)
    return d.strftime("%Y-%m-%d") if d else None


def _as_dirs(value: Path | str | list | tuple) -> list[Path]:
    """Normalise a single folder or a sequence of folders to a list."""
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(v) for v in value]


def tracker_status(
    trackers_dir: Path | str | list | tuple,
    pr_request_dir: Path | str,
) -> dict:
    """What the system currently points at (planner, O&M, PR requests).

    `trackers_dir` may be one folder or an ordered list of folders (the
    upload store plus the Planner's drop folder); see
    `services.tracker_sources` for the folders the app actually uses.
    """
    dirs = _as_dirs(trackers_dir)
    planner, planner_dir = latest_dated_many(dirs, "IHP- Construction Projects")
    om, om_dir = latest_dated_many(dirs, "O&M Project Progress Tracking")
    pr_dir = Path(pr_request_dir)
    pr_files = []
    if pr_dir.is_dir():
        for path in sorted(pr_dir.glob("*.pdf"), key=lambda p: p.name.lower()):
            pr_files.append({
                "filename": path.name,
                "size_kb": round(path.stat().st_size / 1024, 1),
            })
    return {
        "trackers_dir": str(dirs[0]) if dirs else "",
        "trackers_dirs": [str(d) for d in dirs],
        "planner_latest": planner.name if planner else None,
        "planner_path": str(planner) if planner else None,
        "planner_date": _iso_date(planner),
        "planner_dir": str(planner_dir) if planner_dir else None,
        "om_latest": om.name if om else None,
        "om_path": str(om) if om else None,
        "om_date": _iso_date(om),
        "om_dir": str(om_dir) if om_dir else None,
        "pr_request_dir": str(pr_dir),
        "pr_request_dir_exists": pr_dir.is_dir(),
        "pr_request_pdfs": pr_files,
        "pr_request_count": len(pr_files),
        "note": "the system always resolves the newest _DDMMYYYY-dated file",
    }
