"""Cross-tracker consistency checking.

The same project appears in three places, keyed by PR number:

  1. the Planner tracker      (IHP- Construction Projects_DDMMYYYY)
  2. the O&M register         (In House Projects tab - all projects)
  3. the O&M active tabs      (Active Equipment / Active Assessment PRs)

They are maintained by different people, so they drift. This module
compares them and reports every inconsistency with a severity so the
dashboard can raise a blinking alert instead of silently showing
numbers that disagree with the spreadsheets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: Severity order, worst first.
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

#: Planner buckets that mean the work is still early (assessment/design).
_EARLY_BUCKETS = {"EAR", "PROJECT ASSESSMENT", "ASSESSMENT", "DESIGN", "PROCORE", "MTO"}
#: Planner buckets that mean the work is finished.
_DONE_BUCKETS = {"WCC", "WCH"}
#: O&M register statuses that mean the work is finished.
_OM_DONE = {"handover", "completed"}


@dataclass
class Issue:
    """One inconsistency between two tracking sources."""

    code: str
    severity: str
    message: str
    pr_key: str | None = None
    field: str | None = None
    planner_value: str | None = None
    om_value: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "pr_key": self.pr_key,
            "field": self.field,
            "planner_value": self.planner_value,
            "om_value": self.om_value,
        }


@dataclass
class ConsistencyReport:
    total_checked: int = 0
    issues: list[Issue] = field(default_factory=list)

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)

    def summary(self) -> dict:
        by_code: dict[str, int] = {}
        for i in self.issues:
            by_code[i.code] = by_code.get(i.code, 0) + 1
        return {
            "total_checked": self.total_checked,
            "errors": self.count(SEVERITY_ERROR),
            "warnings": self.count(SEVERITY_WARNING),
            "infos": self.count(SEVERITY_INFO),
            "by_code": by_code,
        }

    def to_dict(self, limit: int | None = None) -> dict:
        ordered = sorted(
            self.issues,
            key=lambda i: (_SEVERITY_ORDER.get(i.severity, 9), i.code, i.pr_key or ""),
        )
        if limit is not None:
            ordered = ordered[:limit]
        return {
            "summary": self.summary(),
            "issues": [i.to_dict() for i in ordered],
        }


def _norm_bucket(b: str | None) -> str:
    return (b or "").strip().upper()


def check(planner_rows: Iterable[Any], om_rows: Iterable[Any],
          active_rows: Iterable[Any]) -> ConsistencyReport:
    """Compare the three sources and return every inconsistency found.

    Expected row shapes:
      * planner_rows - services.tracker_import.PlannerRow
      * om_rows      - services.tracker_import.OmRow
      * active_rows  - services.tracker_import.ActivePrRow
    """
    rep = ConsistencyReport()

    planner = {r.pr_key: r for r in planner_rows}
    active = {r.pr_key: r for r in active_rows}
    rep.total_checked = len(planner)

    # --- duplicates inside the Planner -----------------------------------
    seen: dict[str, int] = {}
    for r in planner.values():
        seen[r.pr_key] = seen.get(r.pr_key, 0) + 1

    om_by_pr: dict[str, Any] = {}
    om_dupes: dict[str, int] = {}
    for r in om_rows:
        if r.pr_key in om_by_pr:
            om_dupes[r.pr_key] = om_dupes.get(r.pr_key, 1) + 1
        om_by_pr[r.pr_key] = r
    for pr, n in om_dupes.items():
        rep.issues.append(Issue(
            code="DUPLICATE_OM_ROW", severity=SEVERITY_WARNING,
            message=f"{pr} appears {n} times in the O&M register",
            pr_key=pr, field="PR", om_value=str(n),
        ))

    # --- Planner vs O&M register -----------------------------------------
    for pr, p in planner.items():
        om = om_by_pr.get(pr)
        bucket = _norm_bucket(p.bucket)
        if not bucket:
            rep.issues.append(Issue(
                code="MISSING_BUCKET", severity=SEVERITY_WARNING,
                message=f"{pr} has no Planner bucket (cannot be placed in a division)",
                pr_key=pr, field="Bucket", planner_value="(empty)",
            ))
        if om is None:
            rep.issues.append(Issue(
                code="PLANNER_ONLY", severity=SEVERITY_INFO,
                message=f"{pr} is in the Planner but not in the O&M register",
                pr_key=pr, field="PR", planner_value=bucket or "-",
            ))
            continue

        # Project type: Planner labels vs O&M fund source. Only the two
        # real type tokens are compared - a few O&M rows are column-shifted
        # and carry free text in that cell, which is not a type conflict.
        _TYPES = {"BASELINE", "ASEPC"}
        ptype = _norm_bucket(getattr(p, "project_type", None))
        om_type = _norm_bucket(getattr(om, "fund_source", None))
        if om_type not in _TYPES:
            om_type = ""
        if ptype not in _TYPES:
            ptype = ""
        if ptype and om_type and ptype != om_type:
            rep.issues.append(Issue(
                code="TYPE_MISMATCH", severity=SEVERITY_WARNING,
                message=f"{pr} type differs: Planner says {ptype}, O&M says {om_type}",
                pr_key=pr, field="Type",
                planner_value=ptype, om_value=om_type,
            ))

        # completion state: O&M finished but Planner still early (or vice versa)
        om_status = (getattr(om, "status", None) or "").strip().lower()
        if om_status in _OM_DONE and bucket in _EARLY_BUCKETS:
            rep.issues.append(Issue(
                code="STATUS_MISMATCH", severity=SEVERITY_ERROR,
                message=(f"{pr} is {om_status} in the O&M register but the Planner "
                         f"still buckets it as {bucket}"),
                pr_key=pr, field="Status",
                planner_value=bucket, om_value=om_status.title(),
            ))
        elif om_status == "construction" and bucket in _DONE_BUCKETS:
            rep.issues.append(Issue(
                code="STATUS_MISMATCH", severity=SEVERITY_ERROR,
                message=(f"{pr} is in construction in O&M but the Planner already "
                         f"closed it ({bucket})"),
                pr_key=pr, field="Status",
                planner_value=bucket, om_value="Construction",
            ))

    # --- O&M register rows that the Planner never picked up ---------------
    for pr, om in om_by_pr.items():
        if pr in planner:
            continue
        om_status = (getattr(om, "status", None) or "").strip().lower()
        if om_status == "cancelled":
            continue
        rep.issues.append(Issue(
            code="OM_ONLY", severity=SEVERITY_WARNING,
            message=(f"{pr} is in the O&M register ({om_status or 'no status'}) "
                     f"but not in the Planner file"),
            pr_key=pr, field="PR", om_value=(getattr(om, "status", None) or "-"),
        ))

    # --- active tabs -------------------------------------------------------
    for pr, a in active.items():
        if a.category == "UNKNOWN":
            rep.issues.append(Issue(
                code="UNCLASSIFIED_PR", severity=SEVERITY_ERROR,
                message=(f"{pr} has no IHP Classification of Request in the "
                         f"{a.source_tab} tab"),
                pr_key=pr, field="IHP Classification of Request",
                om_value=(a.classification_raw or "(empty)"),
            ))
        if pr in planner:
            rep.issues.append(Issue(
                code="ACTIVE_ALSO_IN_PLANNER", severity=SEVERITY_INFO,
                message=(f"{pr} is listed in {a.source_tab} and is already in the "
                         f"Planner ({_norm_bucket(planner[pr].bucket) or 'no bucket'})"),
                pr_key=pr, field="PR",
                planner_value=_norm_bucket(planner[pr].bucket),
                om_value=a.source_tab,
            ))

    return rep
