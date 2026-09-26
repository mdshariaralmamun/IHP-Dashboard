"""Planner notes + labels analyser.

Every project row in the Planner tracker carries:
  * Notes      - a chronological free-text progress log. The LAST
    milestone mentioned in it is the project CURRENT status
    (e.g. "... -WCC approved on Oct 16,2024 -WCH approved on NOV 26,2024
    FTD approved" -> current status = FTD Approved, before that WCH).
  * Labels     - semicolon list carrying the TRADE (ELEC, CIVIL, ...),
    the project TYPE (BASELINE / ASEPC) and milestone flags
    (OFFICIAL QUOTATION RECEIVED, RFI DONE, ON HOLD, ...).
  * Checklist Items - "3/6" style completion of the permit/HSE checklist.
  * Priority   - Urgent / Important / Medium.

This module turns those into structured, dashboard-ready values.

Design note - why deterministic parsing instead of an LLM:
the vocabulary here is a small, closed set of milestones with a fixed
grammar, so regex extraction is MORE accurate than a language model and
costs nothing to run. No local model, no API key, no latency. The AI
provider stays available for genuinely open-ended work (chat, summaries).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# Divisions (the four phases of the project lifecycle)
# ---------------------------------------------------------------------------
#
#   EAR          = EAR  (assessment / project summary)
#   Design       = DESIGN + PROCORE + MTO work
#   Construction = PTW/WICF + CONSTRUCTION + SHUTDOWN + QUALITY INSPECTION
#   Close-up     = WCC + WCH + As-Built / Technical Library
#
# Design and Construction are deliberately SEPARATE divisions: design work
# (SOW/BOQ/MTO) is a different team and stage from the field execution work.

PHASE_EAR = "EAR"
PHASE_DESIGN = "Design"
PHASE_CONSTRUCTION = "Construction"
PHASE_CLOSEUP = "Close-up"

#: Planner Bucket -> division. Authoritative when a bucket is present.
BUCKET_TO_PHASE: dict[str, str] = {
    "EAR": PHASE_EAR,
    "PROJECT ASSESSMENT": PHASE_EAR,
    "ASSESSMENT": PHASE_EAR,
    "DESIGN": PHASE_DESIGN,
    "DETAIL DESIGN": PHASE_DESIGN,
    "PROCORE": PHASE_DESIGN,
    "MTO": PHASE_DESIGN,
    "PTW/WICF": PHASE_CONSTRUCTION,
    "PTW": PHASE_CONSTRUCTION,
    "WICF": PHASE_CONSTRUCTION,
    "CONSTRUCTION": PHASE_CONSTRUCTION,
    "SHUTDOWN": PHASE_CONSTRUCTION,
    "QUALITY INSPECTION": PHASE_CONSTRUCTION,
    "WCC": PHASE_CLOSEUP,
    "WCH": PHASE_CLOSEUP,
    "AS-BUILT": PHASE_CLOSEUP,
    "TECHNICAL LIBRARY": PHASE_CLOSEUP,
}

#: Workflow stage -> division. Used for projects that carry no Planner
#: bucket yet (manually created, just imported, or pre-bucket).
STAGE_TO_PHASE: dict[str, str] = {
    "INTAKE": PHASE_EAR,
    "MOM_SENT": PHASE_EAR,
    "MOM_CONFIRMED": PHASE_EAR,
    "DISPOSITION": PHASE_EAR,
    "EAR_DRAFT": PHASE_EAR,
    "EAR_REVIEW": PHASE_EAR,
    "EAR_APPROVED": PHASE_EAR,
    "SOW_DRAFT": PHASE_DESIGN,
    "SOW_REVIEW": PHASE_DESIGN,
    "SOW_APPROVED": PHASE_DESIGN,
    "MTO_DRAFT": PHASE_DESIGN,
    "MTO_APPROVED": PHASE_DESIGN,
    "PROCUREMENT": PHASE_CONSTRUCTION,
    "WORK_PERMIT": PHASE_CONSTRUCTION,
    "CONSTRUCTION": PHASE_CONSTRUCTION,
    "CLOSEOUT": PHASE_CLOSEUP,
    "PUNCH_LIST": PHASE_CLOSEUP,
    "ICR_DONE": PHASE_CLOSEUP,
}

#: Label flags that pull a project into a division when it has no bucket.
#: MTO work belongs to Design; technical-library handover to Close-up.
FLAG_TO_PHASE: dict[str, str] = {
    "MTO": PHASE_DESIGN,
    "TECHNICAL LIBRARY APPROVAL": PHASE_CLOSEUP,
    "AS-BUILT": PHASE_CLOSEUP,
}

PHASES: list[str] = [
    PHASE_EAR, PHASE_DESIGN, PHASE_CONSTRUCTION, PHASE_CLOSEUP,
]


def phase_for_bucket(bucket: str | None) -> str | None:
    """Division for a Planner Bucket value."""
    if not bucket:
        return None
    return BUCKET_TO_PHASE.get(bucket.strip().upper())


def phase_for(bucket: str | None = None, stage: str | None = None,
              flags: list[str] | None = None) -> str | None:
    """Resolve a project division from every signal, most reliable first.

    1. the Planner Bucket (authoritative),
    2. label flags (MTO -> Design, Technical Library -> Close-up),
    3. the workflow stage (for projects with no tracker data yet).
    """
    phase = phase_for_bucket(bucket)
    if phase:
        return phase
    for flag in (flags or []):
        phase = FLAG_TO_PHASE.get(flag.strip().upper())
        if phase:
            return phase
    if stage:
        return STAGE_TO_PHASE.get(stage.strip().upper())
    return None


# ---------------------------------------------------------------------------
# Milestones - the closed vocabulary found in the Notes log
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Milestone:
    key: str            # stable id (used for colours/icons in the UI)
    label: str          # human status shown on the dashboard
    pattern: re.Pattern[str]
    order: int          # higher = later in the delivery sequence


#: The log is chronological, so the LAST match in the text wins.
MILESTONES: tuple[Milestone, ...] = (
    Milestone("cancelled", "Cancelled",
              re.compile(r"\bcancell?ed\b", re.I), 0),
    Milestone("on_hold", "On Hold",
              re.compile(r"\bon\s*hold\b", re.I), 5),
    Milestone("site_visit", "Site Visit",
              re.compile(r"site\s+visit", re.I), 10),
    Milestone("summary_draft", "Project Summary",
              re.compile(r"(project\s+summary|summary\s+(sent|package|draft))", re.I), 15),
    Milestone("ear_approved", "EAR Approved",
              re.compile(r"EAR\s+(was\s+)?(approved|approval)", re.I), 20),
    Milestone("asepc", "ASEPC Approved",
              re.compile(r"ASEPC\s+Approved", re.I), 25),
    Milestone("sow_approved", "SOW Approved",
              re.compile(r"SOW\s+(was\s+)?approved", re.I), 30),
    Milestone("quotation_requested", "Quotation Requested",
              re.compile(r"(request\s+for\s+(official\s+)?quotation|RFQ\s+(sent|issued)|quotation\s+requested)", re.I), 35),
    Milestone("quotation_received", "Official Quotation Received",
              re.compile(r"(official\s+)?quotation\s+(was\s+)?(received|approved|signed)", re.I), 40),
    Milestone("po_issued", "PO Issued",
              re.compile(r"\bPO\b\s*(#|no\.?)?\s*\d{6,}|PO\s+issued", re.I), 45),
    Milestone("exec_summary", "Execution Summary Approved",
              re.compile(r"(project\s+)?execution\s+summary.{0,40}?approved", re.I), 50),
    Milestone("permit", "Permit / WICF Approved",
              re.compile(r"(WICF|permit)\s+(approved|issued|ready)", re.I), 55),
    Milestone("material", "Material Delivered",
              re.compile(r"material(s)?\s+(delivered|received|ready)", re.I), 60),
    Milestone("shutdown", "Shutdown Executed",
              re.compile(r"shutdown\s+(was\s+)?(completed|done|conducted)", re.I), 65),
    Milestone("walkthrough", "Walkthrough",
              re.compile(r"walkthrough", re.I), 70),
    Milestone("wcc_approved", "WCC Approved",
              re.compile(r"WCC\s+(was\s+)?(approved|issued)", re.I), 80),
    Milestone("wch_approved", "WCH Approved",
              re.compile(r"WCH\s+(was\s+)?(approved|issued|signed|routed)", re.I), 90),
    Milestone("ftd_approved", "FTD Approved",
              re.compile(r"FTD\s+(approved|signed)", re.I), 95),
    Milestone("completed", "Completed",
              re.compile(r"\b(completed|work\s+is\s+completed)\b", re.I), 100),
)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

#: "Dec19, 2024" | "JAN 26,2025" | "Oct 2, 2024" | "March 12,2025"
_DATE_MDY = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s*(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(20\d{2})")
#: "15th Oct 2024" | "26 Oct,2025"
_DATE_DMY = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*([A-Za-z]{3,9})\.?\s*,?\s*(20\d{2})")


def _parse_date(text: str) -> datetime | None:
    """Best-effort date parse from a free-text fragment."""
    m = _DATE_MDY.search(text)
    if m:
        month = _MONTHS.get(m.group(1)[:3].lower())
        if month:
            try:
                return datetime(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                pass
    m = _DATE_DMY.search(text)
    if m:
        month = _MONTHS.get(m.group(2)[:3].lower())
        if month:
            try:
                return datetime(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass
    return None


#: Labels that are STATUS flags rather than trades/types.
LABEL_FLAGS: tuple[str, ...] = (
    "OFFICIAL QUOTATION RECEIVED",
    "QUOTATION REQUESTED",
    "WALKTHROUGH COMPLETED",
    "WALKTHROUGH ARRANGED",
    "TECHNICAL LIBRARY APPROVAL",
    "RFI DONE",
    "RFA DONE",
    "WCH ROUTED",
    "FAST TRACK",
    "OPEN BID",
    "ON HOLD",
    "MTO",
    "PDEC",
    "FACULTY",
    "RISP",
    "HSE",
)

#: Trade tokens recognised in Labels.
TRADES: tuple[str, ...] = (
    "CIVIL", "MECH", "ELEC", "PLUMB", "HVAC", "LC", "FIRE", "ARCH",
)

#: Project type tokens recognised in Labels.
TYPES: tuple[str, ...] = ("BASELINE", "ASEPC")


@dataclass
class StatusAnalysis:
    """Structured result of reading one project Notes + Labels."""

    latest_status: str | None = None
    latest_status_key: str | None = None
    latest_status_date: str | None = None          # ISO date
    timeline: list[str] = field(default_factory=list)   # chronological
    flags: list[str] = field(default_factory=list)
    trades: list[str] = field(default_factory=list)
    project_type: str | None = None
    checklist_done: int | None = None
    checklist_total: int | None = None
    phase: str | None = None
    #: Only set for EAR-bucket rows: the funnel step inside the EAR division.
    ear_substatus: str | None = None
    #: Only set for EAR-bucket rows: the date the EAR was approved.
    ear_approved_date: str | None = None

    def as_dict(self) -> dict:
        return {
            "latest_status": self.latest_status,
            "latest_status_key": self.latest_status_key,
            "latest_status_date": self.latest_status_date,
            "timeline": self.timeline,
            "flags": self.flags,
            "trades": self.trades,
            "project_type": self.project_type,
            "checklist_done": self.checklist_done,
            "checklist_total": self.checklist_total,
            "phase": self.phase,
            "ear_substatus": self.ear_substatus,
            "ear_approved_date": self.ear_approved_date,
        }


#: Checklist cell: "3/6", "0 / 2", "5/8"
_CHECKLIST = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")


def parse_labels(labels: str | None) -> tuple[list[str], str | None, list[str]]:
    """Split a Labels cell into (trades, project_type, status_flags)."""
    if not labels:
        return [], None, []
    parts = [p.strip().upper() for p in str(labels).split(";") if p.strip()]
    trades = [p for p in parts if p in TRADES]
    ptype = next((p for p in parts if p in TYPES), None)
    flags = [p for p in parts if p in LABEL_FLAGS]
    return trades, ptype, flags


def analyze_notes(notes: str | None) -> tuple[str | None, str | None, str | None, list[str]]:
    """Read the progress log and return the CURRENT status.

    Returns (label, key, iso_date, timeline).

    The log is chronological, so the milestone appearing LAST in the text is
    the project current state - that is the rule the Planner uses when
    writing these notes ("... WCC approved ... WCH approved ... FTD approved").
    """
    if not notes:
        return None, None, None, []
    text = str(notes)

    hits: list[tuple[int, Milestone, datetime | None, str]] = []
    for ms in MILESTONES:
        for m in ms.pattern.finditer(text):
            window = text[m.end(): m.end() + 40]
            date = _parse_date(window) or _parse_date(text[max(0, m.start() - 30): m.end()])
            hits.append((m.start(), ms, date, m.group(0)))

    if not hits:
        return None, None, None, []

    hits.sort(key=lambda h: h[0])
    # Latest = the last milestone mentioned (dates only fill the date field).
    _, latest_ms, latest_date, _ = hits[-1]

    timeline: list[str] = []
    for _, ms, date, _ in hits:
        entry = ms.label if date is None else f"{ms.label} ({date:%Y-%m-%d})"
        if entry not in timeline:
            timeline.append(entry)

    if latest_date is None:
        dated = [h[2] for h in hits if h[2] is not None]
        latest_date = max(dated) if dated else None

    return (latest_ms.label, latest_ms.key,
            latest_date.strftime("%Y-%m-%d") if latest_date else None,
            timeline)


def analyze(notes: str | None = None, labels: str | None = None,
            checklist: str | None = None, bucket: str | None = None,
            priority: str | None = None) -> StatusAnalysis:
    """Full analysis of one tracker row."""
    out = StatusAnalysis()

    label_, key, date, timeline = analyze_notes(notes)
    out.latest_status = label_
    out.latest_status_key = key
    out.latest_status_date = date
    out.timeline = timeline

    trades, ptype, flags = parse_labels(labels)
    out.trades = trades
    out.project_type = ptype
    out.flags = list(flags)

    # "ON HOLD" living in the Notes is a status too.
    if notes and re.search(r"\bon\s*hold\b", str(notes), re.I):
        if "ON HOLD" not in out.flags:
            out.flags.append("ON HOLD")
        if key is None:
            out.latest_status, out.latest_status_key = "On Hold", "on_hold"

    if checklist:
        m = _CHECKLIST.search(str(checklist))
        if m:
            out.checklist_done = int(m.group(1))
            out.checklist_total = int(m.group(2))

    out.phase = phase_for(bucket=bucket, flags=out.flags)
    # EAR rows get a funnel step so the EAR division can break down into
    # On Hold / EAR Issued / WBS Request / EAR Approved / Awaiting Summary.
    if (bucket or "").strip().upper() == "EAR":
        out.ear_substatus = ear_substatus(notes, out.flags, out.project_type)
        out.ear_approved_date = ear_approved_date(notes)
    return out


#: Regexes for the EAR lifecycle.
_RE_EAR_APPROVED = re.compile(r"ear\s*(?:was\s*)?approved", re.I)
_RE_EAR_ISSUED = re.compile(r"ear\s*(?:was\s*)?(issued|sent|submitt?ed|routed)", re.I)
_RE_ASEPC_APPROVED = re.compile(r"asepc\s*(?:was\s*)?approved", re.I)
_RE_ASEPC_NEEDED = re.compile(r"\basepc\b", re.I)
_RE_ON_HOLD = re.compile(r"\bon\s*hold\b", re.I)
_RE_WBS = re.compile(r"(cost\s*cent(er|re)|\bwbs\b)", re.I)
_RE_SUMMARY = re.compile(r"(summary\s*package|project\s*summary|summary\s*ready)", re.I)
_RE_SITE_VISIT = re.compile(r"site\s*visit", re.I)
#: A project is cancelled when ASEPC does not approve it (or it is dropped).
_RE_CANCELLED = re.compile(
    r"(project\s+cancell?ed|cancell?ed\s+(the\s+)?project|"
    r"not\s+approved|not\s+approve|rejected|declined|dropped\s+the\s+project)",
    re.I,
)
#: The date that belongs to an "EAR approved on <date>" note.
_RE_EAR_APPROVED_DATE = re.compile(
    r"ear\s*(?:was\s*)?approved(?:\s+on)?\s*(.{0,32})", re.I,
)

#: Human labels for the EAR funnel steps.
EAR_SUBSTATUS_LABELS: dict[str, str] = {
    "cancelled": "Cancelled (ASEPC not approved)",
    "on_hold": "On Hold",
    "asepc_pending": "Waiting for ASEPC Approval",
    "ear_approved": "EAR Approved",
    "ear_issued": "EAR Issued",
    "wbs_request": "WBS / Cost Center Request",
    "awaiting_summary": "Awaiting Summary Package",
    "site_visit": "Site Visit Done",
    "asepc_approved": "ASEPC Approved (to construction)",
    "in_progress": "In Progress",
}

#: Display order: what needs attention first.
EAR_SUBSTATUS_ORDER: tuple[str, ...] = (
    "cancelled", "on_hold", "asepc_pending", "ear_approved", "ear_issued",
    "wbs_request", "awaiting_summary", "site_visit", "asepc_approved",
    "in_progress",
)


def ear_approved_date(notes: str | None) -> str | None:
    """The date of the "EAR approved on ..." note (ISO), or None.

    Each project approves on its own date, so this is read straight from the
    progress log rather than derived from a column.
    """
    if not notes:
        return None
    found: datetime | None = None
    for m in _RE_EAR_APPROVED_DATE.finditer(str(notes)):
        parsed = _parse_date(m.group(1)) or _parse_date(
            str(notes)[m.start(): m.start() + 80]
        )
        if parsed and (found is None or parsed > found):
            found = parsed
    return found.strftime("%Y-%m-%d") if found else None


def ear_substatus(notes: str | None, flags: list[str] | None = None,
                  project_type: str | None = None) -> str:
    """Where an EAR project stands, read from its progress log.

    Lifecycle (from the Planner notes):
        site visit -> summary package -> WBS/cost center -> EAR issued ->
        EAR approved -> [ASEPC projects] ASEPC approval -> construction.
        If ASEPC does NOT approve, the project is cancelled.

    Blocked/high-attention states are reported first: a cancelled project is
    never shown as "EAR approved", and an ON HOLD project is never shown by
    its last milestone.
    """
    text = (notes or "")
    label_text = " ".join(flags or [])
    combined = f"{text} {label_text}"
    ptype = (project_type or "").strip().upper()

    if _RE_CANCELLED.search(text):
        return "cancelled"
    if _RE_ON_HOLD.search(combined):
        return "on_hold"

    ear_ok = bool(_RE_EAR_APPROVED.search(text))
    asepc_ok = bool(_RE_ASEPC_APPROVED.search(text))
    needs_asepc = ptype == "ASEPC" or bool(_RE_ASEPC_NEEDED.search(label_text))

    if ear_ok and asepc_ok:
        return "asepc_approved"
    if ear_ok and needs_asepc:
        # EAR is approved but the project cannot start construction until
        # ASEPC approves - and it will be cancelled if they do not.
        return "asepc_pending"
    if ear_ok:
        return "ear_approved"
    if _RE_EAR_ISSUED.search(text):
        return "ear_issued"
    if _RE_WBS.search(combined):
        return "wbs_request"
    if _RE_SUMMARY.search(text):
        return "awaiting_summary"
    if _RE_SITE_VISIT.search(text):
        return "site_visit"
    return "in_progress"


def priority_rank(priority: str | None) -> int:
    """Sort order for priorities: Urgent > Important > Medium > Low."""
    p = (priority or "").strip().lower()
    return {"urgent": 0, "important": 1, "high": 1, "medium": 2, "normal": 2,
            "low": 3}.get(p, 4)
