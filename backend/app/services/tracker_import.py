"""O&M tracker importer + planner/O&M mismatch detector.

The O&M tracking file (" In House Projects" sheet) and the MS Project
planner file are both live sources for the same set of projects. This
module parses either, and emits a per-PR mismatch report so the user can
decide which is the real data.

Design notes
------------
* Pure functions for parsing — no DB writes. The HTTP layer runs the
  parsers, then either applies the import (planner only) or just stores
  the parsed result for the mismatch report (O&M only).
* The mismatch report is keyed on the planner's PR-number format
  ("PR-1234"). The O&M file uses bare integers ("1234"); we normalise.
* A mismatch is reported when the two sources disagree on a field, OR
  when one source has the project and the other doesn't. Missing data
  in one source is not a mismatch — only *conflicting* data is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import openpyxl


# ---------------------------------------------------------------------------
# PR-number normalisation
# ---------------------------------------------------------------------------

_PR_HEAD = re.compile(r"^(?:PR[\s\-]*)?(\d{4,6})\b", re.IGNORECASE)


def _to_pr_key(s: str | int | None) -> str | None:
    """Normalise a PR number to `PR-<digits>` form. Returns None if
    the input can't be parsed.
    """
    if s is None or s == "":
        return None
    raw = str(s).strip()
    m = _PR_HEAD.match(raw)
    if m:
        return f"PR-{m.group(1)}"
    # bare digits
    if raw.isdigit():
        return f"PR-{raw}"
    return None


# ---------------------------------------------------------------------------
# Markdown exports
# ---------------------------------------------------------------------------

#: Table separator row: | --- | --- |
_MD_SEP = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")


def _md_cell(v: Any) -> Any:
    """Normalise one markdown-table cell.

    The pandas markdown dumps use "NaN" / "Unnamed: N" placeholders for
    empty cells; both must become None so the row mappers treat them as
    missing rather than as literal strings.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "nat"}:
        return None
    if s.startswith("Unnamed:"):
        return None
    return s


def md_tables(path: Path | str) -> dict[str, list[list[Any]]]:
    """Parse a pandas-style markdown dump into ``{sheet_name: rows}``.

    Each ``## <name>`` heading starts a sheet, followed by a pipe table
    whose first row is the header and second row the ``| --- |`` separator.
    The header and separator rows are dropped; remaining rows are returned
    as lists of normalised cells (`_md_cell`). The same column indices as
    the .xlsx export are preserved, so the row mappers are shared.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    tables: dict[str, list[list[Any]]] = {}
    sheet: str | None = None
    rows: list[list[Any]] = []
    seen_header = False

    def flush() -> None:
        if sheet is not None:
            tables[sheet] = rows

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            sheet = line[3:].strip()
            rows = []
            seen_header = False
            continue
        if sheet is None:
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if _MD_SEP.match(stripped):
            seen_header = True
            continue
        if not seen_header:
            continue  # column header row
        cells = [_md_cell(c) for c in stripped.strip("|").split("|")]
        if any(c is not None for c in cells):
            rows.append(cells)
    flush()
    return tables


def md_sheet(path: Path | str, sheet: str) -> list[list[Any]]:
    """Rows of one named sheet in a markdown dump.

    Falls back to a case-insensitive match, then to the first table, so a
    heading rename in the export never breaks the import.
    """
    tables = md_tables(path)
    if sheet in tables:
        return tables[sheet]
    wanted = sheet.strip().lower()
    for name, rows in tables.items():
        if name.strip().lower() == wanted:
            return rows
    return next(iter(tables.values()), [])

@dataclass
class PlannerRow:
    pr_key: str
    name: str
    bucket: str
    percent: float | None
    division: str | None
    building: str | None
    pi_name: str | None
    priority: str | None
    sprint: str | None
    effort: str | None
    duration: str | None
    start: str | None
    finish: str | None
    labels: str | None
    milestone: str | None
    checklist: str | None
    trade: str | None  # first recognised trade from labels
    project_type: str | None  # BASELINE / ASEPC from labels
    #: IHP engineer the task is assigned to (Planner "Assigned to" column).
    assigned_to: str | None
    execution_lead: str | None
    requestor: str | None  # Planner "Requestor/PI" column


_TRADE_TOKENS = {"CIVIL", "MECH", "ELEC", "PLUMB", "HVAC", "LC", "FIRE", "ARCH"}
_TYPE_TOKENS = {"BASELINE", "ASEPC"}


def _labels_to_tokens(label_str: str | None) -> tuple[str | None, str | None]:
    if not label_str:
        return None, None
    parts = [p.strip().upper() for p in label_str.split(";") if p.strip()]
    trade = next((p for p in parts if p in _TRADE_TOKENS), None)
    type_ = next((p for p in parts if p in _TYPE_TOKENS), None)
    return trade, type_


def sheet_rows(path: Path | str, sheet: str, start_row: int = 2,
               min_cols: int = 0) -> list[list[Any]]:
    """Data rows of one sheet from EITHER an .xlsx or a .md tracker export.

    `start_row` is the 1-based first data row for .xlsx (the markdown dumps
    already exclude their header). Rows are padded to `min_cols` so the
    shared column-index mappers never hit an IndexError on a short markdown
    row. This is what lets the newest `_DDMMYYYY.md` export feed exactly the
    same parsers as the .xlsx one.
    """
    path = Path(path)
    if path.suffix.lower() == ".md":
        rows = md_sheet(path, sheet)
    else:
        wb = openpyxl.load_workbook(path, data_only=True)
        if sheet in wb.sheetnames:
            ws = wb[sheet]
        else:
            ws = wb[wb.sheetnames[0]]
        rows = [
            [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
            for r in range(start_row, ws.max_row + 1)
        ]
    if min_cols:
        for row in rows:
            while len(row) < min_cols:
                row.append(None)
    return rows


def parse_planner(path: Path) -> list[PlannerRow]:
    """Read the MS Project export and return a list of PlannerRow.

    Accepts the .xlsx export (header block in rows 1-9, data from row 10)
    and the .md markdown dump of the same sheet. Empty Name cells are
    skipped. Bucket is uppercased + stripped.
    """
    out: list[PlannerRow] = []
    for cells in sheet_rows(path, "Project tasks", start_row=10, min_cols=28):
        if not any(c is not None for c in cells):
            continue
        name = (cells[2] or "").strip() if cells[2] else ""
        if not name:
            continue
        pr_key = _to_pr_key(name)
        if not pr_key:
            continue

        bucket = (cells[4] or "").strip().upper() if cells[4] else ""
        labels = (cells[21] or "").strip() if cells[21] else ""
        trade, type_ = _labels_to_tokens(labels)

        def _s(v):
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        def _pct(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _iso(v):
            if hasattr(v, "strftime"):
                return v.strftime("%Y-%m-%d")
            s = _s(v)
            # Markdown dumps carry datetimes as "2024-06-13 09:00:00".
            if s and len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
                return s[:10]
            return s

        out.append(PlannerRow(
            pr_key=pr_key,
            name=name,
            bucket=bucket,
            percent=_pct(cells[11]),
            division=_s(cells[6]),
            building=_s(cells[25]),
            # Columns (header row 9): 3 = "Assigned to", 26 = "Execution Lead",
            # 27 = "Requestor/PI". Cell 3 was previously read as the PI, which
            # put an IHP engineer into the PI field; the PI comes from the PR
            # intake form, so it is no longer taken from here.
            assigned_to=_s(cells[3]),
            pi_name=None,
            priority=_s(cells[22]),
            sprint=_s(cells[23]),
            effort=_s(cells[13]),
            duration=_s(cells[16]),
            start=_iso(cells[9]),
            finish=_iso(cells[7]),
            labels=labels or None,
            milestone=_s(cells[17]),
            checklist=_s(cells[20]),
            trade=trade,
            project_type=type_,
            execution_lead=_s(cells[26]),
            requestor=_s(cells[27]),
        ))
    return out


# ---------------------------------------------------------------------------
# O&M parsing
# ---------------------------------------------------------------------------

@dataclass
class OmRow:
    pr_key: str
    title: str
    division: str | None
    requestor: str | None
    location: str | None          # col 7: "Academic Building 2 - Ibn Al-Haytham Building"
    location_details: str | None  # col 8: "Building 2, Level 0, Sea side"
    manager: str | None
    project_controls: str | None
    execution_lead: str | None
    status: str | None            # IHP / Construction / Feasibility Study / etc.
    request_date: str | None
    plan_start: str | None
    plan_finish: str | None
    actual_start: str | None
    actual_finish: str | None
    cost_estimate_usd: str | None
    progress_pct: str | None
    fund_source: str | None
    contractor: str | None
    wbs: str | None
    po_number: str | None
    remarks: str | None
    # Stage mapping (O&M "Status" -> IHP stage, best-effort)
    stage: str | None
    disposition: str | None


#: Map O&M "Status" values to IHP workflow stages
_OM_STATUS_TO_STAGE: dict[str, tuple[str, str | None]] = {
    "completed":     ("CLOSEOUT",      "PROJECT"),
    "construction":  ("CONSTRUCTION",  "PROJECT"),
    "ihp":           ("SOW_APPROVED",  "PROJECT"),
    "bidding/tender":("PROCUREMENT",   "PROJECT"),
    "feasibility study": ("INTAKE",    "PROJECT"),
    "cancelled":     ("INTAKE",        None),
    "on hold":       ("INTAKE",        None),
    "design":        ("EAR_REVIEW",    "PROJECT"),
}


def _om_status_to_stage(s: str | None) -> tuple[str | None, str | None]:
    if not s:
        return None, None
    k = s.strip().lower()
    return _OM_STATUS_TO_STAGE.get(k, (None, None))


def parse_om(path: Path, sheet: str = " In House Projects") -> list[OmRow]:
    """Read the O&M tracker and return a list of OmRow.

    The O&M file has 8 sheets. The ' In House Projects' sheet is the
    main project register (277 rows × 33 columns). The PR number is
    in col 1 as a plain integer.
    """
    path = Path(path)
    if path.suffix.lower() != ".md":
        wb = openpyxl.load_workbook(path, data_only=True)
        if sheet not in wb.sheetnames:
            raise ValueError(
                f"O&M sheet {sheet!r} not found. Available: {wb.sheetnames}")

    out: list[OmRow] = []
    # xlsx: header is row 1, data from row 2. md: header already stripped.
    for cells in sheet_rows(path, sheet, start_row=2, min_cols=33):
        if not any(c is not None for c in cells):
            continue
        pr_raw = cells[0]
        pr_key = _to_pr_key(pr_raw)
        if not pr_key:
            continue

        def _s(v):
            if v is None:
                return None
            t = str(v).strip()
            return t or None

        def _iso(v):
            if hasattr(v, "strftime"):
                return v.strftime("%Y-%m-%d")
            s = _s(v)
            # Markdown dumps carry datetimes as "2024-06-13 09:00:00".
            if s and len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
                return s[:10]
            return s

        status = _s(cells[11])
        stage, disposition = _om_status_to_stage(status)

        out.append(OmRow(
            pr_key=pr_key,
            title=_s(cells[3]) or "",
            division=_s(cells[4]),
            requestor=_s(cells[5]),
            location=_s(cells[6]),
            location_details=_s(cells[7]),
            manager=_s(cells[8]),
            project_controls=_s(cells[9]),
            execution_lead=_s(cells[10]),
            status=status,
            request_date=_iso(cells[2]),
            plan_start=_iso(cells[17]),
            plan_finish=_iso(cells[18]),
            actual_start=_iso(cells[19]),
            actual_finish=_iso(cells[20]),
            cost_estimate_usd=_s(cells[12]),
            progress_pct=_s(cells[23]),
            fund_source=_s(cells[27]),
            contractor=_s(cells[22]),
            wbs=_s(cells[28]),
            po_number=_s(cells[29]),
            remarks=_s(cells[25]) or _s(cells[26]),
            stage=stage,
            disposition=disposition,
        ))
    return out


# ---------------------------------------------------------------------------
# Mismatch detection
# ---------------------------------------------------------------------------

@dataclass
class FieldMismatch:
    field: str
    planner: Any
    om: Any

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PrMismatch:
    pr_key: str
    in_planner: bool
    in_om: bool
    in_db: bool
    db_stage: str | None = None
    db_location: str | None = None
    db_pi_name: str | None = None
    db_division: str | None = None
    planner_title: str | None = None
    om_title: str | None = None
    db_title: str | None = None
    mismatches: list[FieldMismatch] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mismatches"] = [m.to_dict() for m in self.mismatches]
        return d


#: Fields to compare between the two sources. Each entry is
#: (field_name, planner_attr, om_attr, normaliser). A normaliser returns
#: a comparable value or None to skip.
def _norm_lower(s):
    return (s or "").strip().lower() or None


def _norm_pi(s):
    """PI names are messy in both files ('John Rahmer' vs 'J. Rahmer').
    Compare case-insensitively on the last word as a fallback."""
    if not s:
        return None
    s = s.strip().lower()
    return s


def _norm_pct(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    try:
        return round(float(s), 2)
    except (TypeError, ValueError):
        return None


_COMPARE_FIELDS: list[tuple[str, str, str, callable, callable]] = [
    # (key, planner_attr, om_attr, planner_norm, om_norm)
    # pi_name no longer compared against O&M requestor (which contains IHP team members).
    # PI is sourced from PR intake form and stored directly in DB; mismatches
    # for pi_name are handled via the manual override flow instead.
    ("location",  "building",      "location",     _norm_lower, _norm_lower),
    ("division",  "division",      "division",     _norm_lower, _norm_lower),
    ("start",     "start",         "plan_start",   _norm_lower, _norm_lower),
    ("finish",    "finish",        "plan_finish",  _norm_lower, _norm_lower),
]


def compare(
    planner_rows: list[PlannerRow],
    om_rows: list[OmRow],
    db_projects: list[dict],
) -> list[PrMismatch]:
    """Build a per-PR mismatch report from the two parsed trackers
    and the current DB state.

    `db_projects` is a list of dicts with at least
    `pr_number, title, stage, location, pi_name, division` keys
    (the output of `SELECT` over the `projects` table).

    A mismatch is reported when:
      * the same PR is in both sources but a field disagrees, OR
      * the PR is in the planner but missing from the O&M (or vice versa),
        AND it's in the DB (so the user has a stake in the row).

    Pure-PR differences (planner-only or O&M-only with no DB row) are
    reported as "missing_in_other" with no field comparisons.
    """
    planner_by_pr = {r.pr_key: r for r in planner_rows}
    om_by_pr = {r.pr_key: r for r in om_rows}
    db_by_pr = {p["pr_number"]: p for p in db_projects}

    all_keys = set(planner_by_pr) | set(om_by_pr) | set(db_by_pr)
    out: list[PrMismatch] = []

    for pr_key in sorted(all_keys):
        p = planner_by_pr.get(pr_key)
        o = om_by_pr.get(pr_key)
        d = db_by_pr.get(pr_key)
        if d is None and p is None and o is None:
            continue
        if p is None and o is None:
            continue

        rec = PrMismatch(
            pr_key=pr_key,
            in_planner=p is not None,
            in_om=o is not None,
            in_db=d is not None,
            db_stage=(d or {}).get("stage"),
            db_location=(d or {}).get("location"),
            db_pi_name=(d or {}).get("pi_name"),
            db_division=(d or {}).get("division"),
            planner_title=p.name if p else None,
            om_title=o.title if o else None,
            db_title=(d or {}).get("title"),
        )
        if p and o:
            for fld, p_attr, o_attr, p_norm, o_norm in _COMPARE_FIELDS:
                p_val = p_norm(getattr(p, p_attr))
                o_val = o_norm(getattr(o, o_attr))
                if p_val is None or o_val is None:
                    continue  # one side missing -> not a mismatch
                if p_val != o_val:
                    rec.mismatches.append(FieldMismatch(
                        field=fld,
                        planner=getattr(p, p_attr),
                        om=getattr(o, o_attr),
                    ))
        out.append(rec)
    return out


def summarise(mismatches: list[PrMismatch]) -> dict:
    """Return counts for the report header."""
    total = len(mismatches)
    in_planner = sum(1 for m in mismatches if m.in_planner)
    in_om = sum(1 for m in mismatches if m.in_om)
    in_db = sum(1 for m in mismatches if m.in_db)
    with_conflicts = sum(1 for m in mismatches if m.mismatches)
    missing_in_om = sum(1 for m in mismatches if m.in_planner and not m.in_om and m.in_db)
    missing_in_planner = sum(1 for m in mismatches if m.in_om and not m.in_planner and m.in_db)
    by_field: dict[str, int] = {}
    for m in mismatches:
        for fm in m.mismatches:
            by_field[fm.field] = by_field.get(fm.field, 0) + 1
    return {
        "total": total,
        "in_planner": in_planner,
        "in_om": in_om,
        "in_db": in_db,
        "with_conflicts": with_conflicts,
        "missing_in_om": missing_in_om,
        "missing_in_planner": missing_in_planner,
        "conflicts_by_field": by_field,
    }

# ---------------------------------------------------------------------------
# O&M active-PR register (classification + IHP remarks)
# ---------------------------------------------------------------------------
#
# The O&M workbook splits active work into two tabs:
#   * "Active Equipment PRs"           - equipment-focused requests
#   * "Active Project Assessment PRs"  - requests awaiting assessment
# Both carry "IHP Classification of Request" and "IHP Remarks" columns.
# The classification decides whether a PR belongs to the IHP construction
# stream or to the separate equipment-installation branch (equipment-only
# work against an existing lab: no modification, no utility tie-in), which
# must NOT be counted in the IHP active data.

#: Raw classification text -> stable category.
CLASSIFICATION_MAP: dict[str, str] = {
    "construction project": "CONSTRUCTION",
    "contruction project": "CONSTRUCTION",   # typo present in the source
    "construction": "CONSTRUCTION",
    "equipment installation": "EQUIPMENT_INSTALLATION",
    "equipment instalation": "EQUIPMENT_INSTALLATION",
    "equipment assessment": "EQUIPMENT_ASSESSMENT",
    "assessment of lab eqpt": "EQUIPMENT_ASSESSMENT",
    "assessment of lab equipment": "EQUIPMENT_ASSESSMENT",
    "asepc proposal request": "ASEPC_PROPOSAL",
    "icr": "ICR",
}

#: Categories that count as IHP construction work (the active data).
IHP_ACTIVE_CATEGORIES: frozenset[str] = frozenset({"CONSTRUCTION"})
#: Categories owned by the equipment branch - excluded from IHP counts.
EQUIPMENT_CATEGORIES: frozenset[str] = frozenset(
    {"EQUIPMENT_INSTALLATION", "EQUIPMENT_ASSESSMENT", "ICR"}
)
#: Assessment-only requests (EAR / project-assessment phase).
ASSESSMENT_CATEGORIES: frozenset[str] = frozenset({"ASEPC_PROPOSAL"})


def classify_request(raw: str | None) -> str:
    """Normalise an "IHP Classification of Request" cell to a category."""
    if not raw:
        return "UNKNOWN"
    key = str(raw).strip().lower().rstrip("-").strip()
    if key in CLASSIFICATION_MAP:
        return CLASSIFICATION_MAP[key]
    for probe, category in CLASSIFICATION_MAP.items():
        if key.startswith(probe):
            return category
    return "UNKNOWN"


@dataclass
class ActivePrRow:
    """One row of the O&M active-PR tabs."""

    pr_key: str
    source_tab: str
    title: str | None
    division: str | None
    requestor: str | None
    location: str | None
    status: str | None
    classification_raw: str | None
    category: str
    remarks: str | None
    request_date: str | None

    def to_dict(self) -> dict:
        return asdict(self)


#: Tabs that hold the active-PR registers.
OM_ACTIVE_TABS: tuple[str, ...] = (
    "Active Equipment PRs",
    "Active Project Assessment PRs",
)


def _header_index(rows: list[list[Any]], first_cell: str) -> int | None:
    """Index of the real header row (first cell matches `first_cell`)."""
    for i, row in enumerate(rows[:6]):
        if row and str(row[0] or "").strip().lower() == first_cell.lower():
            return i
    return None


def parse_om_active_prs(path: Path | str,
                        tabs: tuple[str, ...] = OM_ACTIVE_TABS) -> list[ActivePrRow]:
    """Parse the O&M active-PR tabs (equipment + assessment).

    Both tabs put a section-label row above the real header, so the header is
    located by looking for a row starting with "PR" (works for the .md dump
    and the .xlsx export alike).
    """
    path = Path(path)
    out: list[ActivePrRow] = []

    for tab in tabs:
        try:
            rows = sheet_rows(path, tab, start_row=2, min_cols=29)
        except Exception:  # noqa: BLE001 - a missing tab must not break the rest
            continue
        if not rows:
            continue
        head = _header_index(rows, "PR")
        if head is None:
            head = _header_index(rows, "PR Number")
        data = rows[(head + 1):] if head is not None else rows

        def _s(v: Any) -> str | None:
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        for cells in data:
            pr_key = _to_pr_key(cells[0] if cells else None)
            if not pr_key:
                continue
            raw_class = _s(cells[28]) if len(cells) > 28 else None
            out.append(ActivePrRow(
                pr_key=pr_key,
                source_tab=tab,
                title=_s(cells[3]) if len(cells) > 3 else None,
                division=_s(cells[4]) if len(cells) > 4 else None,
                requestor=_s(cells[5]) if len(cells) > 5 else None,
                location=_s(cells[6]) if len(cells) > 6 else None,
                status=_s(cells[10]) if len(cells) > 10 else None,
                classification_raw=raw_class,
                category=classify_request(raw_class),
                remarks=_s(cells[27]) if len(cells) > 27 else None,
                request_date=_s(cells[2]) if len(cells) > 2 else None,
            ))
    return out


def summarise_active_prs(rows: list[ActivePrRow]) -> dict:
    """Counts split into IHP-active vs the excluded equipment branch."""
    ihp = [r for r in rows if r.category in IHP_ACTIVE_CATEGORIES]
    equipment = [r for r in rows if r.category in EQUIPMENT_CATEGORIES]
    assessment = [r for r in rows if r.category in ASSESSMENT_CATEGORIES]
    unknown = [r for r in rows if r.category == "UNKNOWN"]
    by_tab: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for r in rows:
        by_tab[r.source_tab] = by_tab.get(r.source_tab, 0) + 1
        by_category[r.category] = by_category.get(r.category, 0) + 1
    return {
        "total": len(rows),
        "ihp_active_count": len(ihp),
        "equipment_branch_count": len(equipment),
        "assessment_count": len(assessment),
        "unknown_count": len(unknown),
        "by_tab": by_tab,
        "by_category": by_category,
    }

