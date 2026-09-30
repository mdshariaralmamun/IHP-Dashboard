"""Latest-dated tracker resolution tests (services/tracker_files.py)."""

from datetime import datetime
from pathlib import Path

from app.services.tracker_files import (
    ensure_dated, latest_dated, latest_dated_many, tracker_status,
)


def _touch(directory: Path, name: str) -> Path:
    p = directory / name
    p.write_bytes(b"x")
    return p


def test_newest_ddmmyyyy_wins(tmp_path):
    _touch(tmp_path, "IHP- Construction Projects_07092026.xlsx")
    newest = _touch(tmp_path, "IHP- Construction Projects_15092026.xlsx")
    assert latest_dated(tmp_path, "IHP- Construction Projects") == newest


def test_iso_dated_files_supported(tmp_path):
    newest = _touch(tmp_path, "DSR_PRJ-MARINA-01_2026-09-16.xlsx")
    _touch(tmp_path, "DSR_PRJ-MARINA-01_2026-08-27.xlsx")
    assert latest_dated(tmp_path, "DSR_PRJ") == newest


def test_prefix_match_is_case_insensitive_and_ignores_other_files(tmp_path):
    newest = _touch(tmp_path, "o&m project progress tracking sheet sep 2025_15092026.xlsx")
    _touch(tmp_path, "IHP- Construction Projects_07092026.xlsx")
    assert latest_dated(tmp_path, "O&M Project Progress Tracking") == newest


def test_single_undated_fallback_and_missing_dir(tmp_path):
    only = _touch(tmp_path, "IHP - Cost Estimates file -1.md")
    assert latest_dated(tmp_path, "IHP - Cost Estimates", ".md") == only
    assert latest_dated(tmp_path / "nope", "x") is None


def test_newer_md_export_beats_older_xlsx(tmp_path):
    """The real-world case: the Planner exports .md for the newest date only.

    The older .xlsx must never shadow the newer .md, otherwise the app keeps
    showing stale tracker data.
    """
    _touch(tmp_path, "IHP- Construction Projects_21092026.xlsx")
    newest = _touch(tmp_path, "IHP- Construction Projects_26092026.md")
    assert latest_dated(tmp_path, "IHP- Construction Projects") == newest


def test_same_date_prefers_xlsx(tmp_path):
    """For one date, both formats exist: prefer the richer .xlsx export."""
    xlsx = _touch(tmp_path, "IHP- Construction Projects_26092026.xlsx")
    _touch(tmp_path, "IHP- Construction Projects_26092026.md")
    assert latest_dated(tmp_path, "IHP- Construction Projects") == xlsx


def test_explicit_suffix_restricts_formats(tmp_path):
    md = _touch(tmp_path, "IHP- Construction Projects_26092026.md")
    _touch(tmp_path, "IHP- Construction Projects_21092026.xlsx")
    assert latest_dated(tmp_path, "IHP- Construction Projects", ".md") == md


def test_status_lists_pr_request_pdfs(tmp_path):
    pr_dir = tmp_path / "PR Request Copy"
    pr_dir.mkdir()
    (pr_dir / "PR 12693 request.pdf").write_bytes(b"x")
    (pr_dir / "notes.txt").write_bytes(b"x")
    status = tracker_status(tmp_path, pr_dir)
    assert status["planner_latest"] is None
    assert [f["filename"] for f in status["pr_request_pdfs"]] == ["PR 12693 request.pdf"]
    assert status["pr_request_count"] == 1


# --- multi-folder resolution (interfaces with services/tracker_sources) -----


def test_many_dirs_newer_file_in_the_second_folder_wins(tmp_path):
    """The upload store is searched first, but "first" must not mean
    "wins regardless of date": a newer export in the Planner's drop folder
    still takes over."""
    store = tmp_path / "store"
    store.mkdir()
    drop = tmp_path / "drop"
    drop.mkdir()
    _touch(store, "IHP- Construction Projects_21092026.xlsx")
    newest = _touch(drop, "IHP- Construction Projects_26092026.xlsx")
    path, folder = latest_dated_many([store, drop], "IHP- Construction Projects")
    assert path == newest
    assert folder == drop


def test_many_dirs_first_folder_wins_a_date_tie(tmp_path):
    """Same date in both folders: the upload (listed first) is the version."""
    store = tmp_path / "store"
    store.mkdir()
    drop = tmp_path / "drop"
    drop.mkdir()
    uploaded = _touch(store, "IHP- Construction Projects_26092026.xlsx")
    _touch(drop, "IHP- Construction Projects_26092026.xlsx")
    assert latest_dated_many(
        [store, drop], "IHP- Construction Projects"
    ) == (uploaded, store)


def test_many_dirs_skips_missing_folders_and_reports_none(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    only = _touch(drop, "O&M Project Progress Tracking Sheet Sep 2025_26092026.md")
    assert latest_dated_many(
        [tmp_path / "missing", drop], "O&M Project Progress Tracking"
    ) == (only, drop)
    assert latest_dated_many([tmp_path / "missing"], "O&M") == (None, None)


def test_ensure_dated_keeps_dated_names_and_stamps_the_rest():
    assert ensure_dated("IHP- Construction Projects_26092026.xlsx") == (
        "IHP- Construction Projects_26092026.xlsx"
    )
    assert ensure_dated(
        "IHP- Construction Projects.xlsx", datetime(2026, 9, 30)
    ) == "IHP- Construction Projects_30092026.xlsx"


def test_ensure_dated_cannot_escape_the_store_directory():
    assert ensure_dated("../../etc/passwd.xlsx", datetime(2026, 9, 30)) == (
        "passwd_30092026.xlsx"
    )
