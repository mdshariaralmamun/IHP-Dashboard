"""Project Summary generator - the official IHP house format.

Format extracted from the standard example
(E:\ENGINEERING_DATA\IHP Project Format\PR-12545 Project Summary.docx):

    Date: <today>
    To: <PI name>
    +--------------------------------------------------------------+
    | Project Reference: | PR <n> <title>                          |
    | Division:          | <division>                              |
    | Customer/Proponent:| <PI name>                               |
    | Contact:           | <PI email>                              |
    | Project Location   | <building / location details>           |
    +--------------------------------------------------------------+
    Introduction            (KAUST standard wording, project-specific)
    General Scope of Work   (bold trade headings + bullet items)
    +--------------------------------------------------------------+
    | Scope:                             | Attached                 |
    | TOTAL ESTIMATED PROJECT COST       | Within IHP budget        |
    | WBS:                               | <WBS if known>           |
    +--------------------------------------------------------------+
    +--------------------------------------------------------------+
    | Detailed Design             | n Weeks                        |
    | Materials Order and Delivery| n Weeks                        |
    | Construction Works          | n Weeks                        |
    | Handing over                | n Weeks                        |
    | Total                       | n Weeks                        |
    +--------------------------------------------------------------+

Every field is variable and filled from the project context (register row,
O&M location details, BOQ trade items and the Planner schedule).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches

from ..db import SessionLocal
from ..models import BoqMtoItem, Project
from .storage import project_dir


INTRO = (
    "King Abdullah University of Science & Technology (KAUST) intends to "
    "proceed with the subject project. This Project Summary describes the "
    "proposed scope of work to be executed by the In-House Projects (IHP) "
    "team, based on the site assessment and the requirements agreed with "
    "the proponent."
)

#: Trade display order used by the house format.
TRADE_ORDER = [
    ("Civil/Architectural", ["CIVIL", "ARCH", "Civil/Architectural"]),
    ("Electrical", ["ELEC", "Electrical"]),
    ("Low Current / Telecommunication", ["LC", "Low Current"]),
    ("Plumbing", ["PLUMB", "Plumbing"]),
    ("HVAC", ["HVAC", "HVAC"]),
    ("Fire Sprinkler System", ["FIRE", "Fire"]),
    ("TGM", ["TGM", "Gas Detection"]),
    ("Mechanical", ["MECH", "Mechanical"]),
]


def _weeks_between(start: str | None, finish: str | None) -> int | None:
    if not start or not finish:
        return None
    try:
        from datetime import datetime
        s = datetime.fromisoformat(str(start)[:10])
        f = datetime.fromisoformat(str(finish)[:10])
        w = round(max((f - s).days, 0) / 7) or 1
        return w
    except ValueError:
        return None


def _trade_items(db, project_id: int) -> dict[str, list[str]]:
    """Scope lines per trade, from the BOQ/MTO items of this project."""
    out: dict[str, list[str]] = {}
    items = db.query(BoqMtoItem).filter(BoqMtoItem.project_id == project_id).all()
    for it in items:
        trade = (it.trade or "General").strip()
        desc = (it.description or "").strip()
        if not desc:
            continue
        out.setdefault(trade, [])
        if desc not in out[trade]:
            out[trade].append(desc)
    return out


def _match_trade(name: str) -> str | None:
    n = (name or "").upper()
    for label, keys in TRADE_ORDER:
        if any(k.upper() in n for k in keys):
            return label
    return None


def generate_project_summary_docx(project: Project, context: dict | None = None,
                                  db=None) -> Path:
    """Write the Project Summary in the official house format and return it."""
    from ..api.projects import _derive_tracker_fields

    own_db = db is None
    db = db or SessionLocal()
    try:
        d = _derive_tracker_fields(project)
        ctx = context or {}
        pi_name = project.pi_name or ctx.get("pi_name")
        pi_email = project.pi_email or ctx.get("pi_email")
        location = project.location or ctx.get("location") or "-"
        loc_details = ctx.get("location_details")
        division = ctx.get("division") or d.get("division") or "-"

        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(11)

        # ---- KAUST logo -------------------------------------------------------
        logo = Path(__file__).resolve().parents[1] / "templates" / "kaust_logo.png"
        if logo.is_file():
            doc.add_picture(str(logo), width=Inches(1.6))
            doc.paragraphs[-1].alignment = 1  # centred

        # ---- header ----------------------------------------------------------
        doc.add_paragraph(f"Date: {date.today().strftime('%d %B %Y')}")
        doc.add_heading(f"To:  {pi_name or '-'}", level=2)

        # ---- project info block ----------------------------------------------
        t1 = doc.add_table(rows=5, cols=2)
        t1.style = "Table Grid"
        rows = [
            ("Project Reference:", f"{project.pr_number} {project.title}"),
            ("Division:", division),
            ("Customer/ Proponent:", pi_name or "-"),
            ("Contact:", pi_email or "-"),
            ("Project Location", (location + (f" - {loc_details}" if loc_details else ""))),
        ]
        for i, (k, v) in enumerate(rows):
            t1.cell(i, 0).text = k
            t1.cell(i, 1).text = str(v)
            t1.cell(i, 0).paragraphs[0].runs[0].bold = True

        doc.add_paragraph()

        # ---- introduction ------------------------------------------------------
        p = doc.add_paragraph()
        r = p.add_run("Introduction")
        r.bold = True
        doc.add_paragraph(INTRO)

        # ---- general scope of work --------------------------------------------
        p = doc.add_paragraph()
        r = p.add_run("General Scope of Work")
        r.bold = True

        by_trade = _trade_items(db, project.id)
        matched: dict[str, list[str]] = {}
        unmatched: dict[str, list[str]] = {}
        for trade, lines in by_trade.items():
            label = _match_trade(trade)
            if label:
                matched.setdefault(label, []).extend(lines)
            else:
                unmatched.setdefault(trade, []).extend(lines)
        if not matched and not unmatched:
            doc.add_paragraph(
                "(Scope items will appear here once the BOQ/MTO is prepared.)")
        for label, _keys in TRADE_ORDER:
            lines = matched.get(label)
            if not lines:
                continue
            doc.add_paragraph(label).runs[0].bold = True
            for line in lines[:20]:
                doc.add_paragraph(line, style="List Bullet")
        for trade, lines in unmatched.items():
            doc.add_paragraph(trade).runs[0].bold = True
            for line in lines[:20]:
                doc.add_paragraph(line, style="List Bullet")

        # ---- commercial block ---------------------------------------------------
        doc.add_paragraph()
        t2 = doc.add_table(rows=3, cols=2)
        t2.style = "Table Grid"
        rows = [
            ("Scope:", "Attached"),
            ("TOTAL ESTIMATED PROJECT COST", "Within IHP budget"),
            ("WBS:", "-"),
        ]
        for i, (k, v) in enumerate(rows):
            t2.cell(i, 0).text = k
            t2.cell(i, 1).text = v
            t2.cell(i, 0).paragraphs[0].runs[0].bold = True

        # ---- schedule block ------------------------------------------------------
        doc.add_paragraph()
        total_weeks = _weeks_between(d.get("start_date"), d.get("finish_date"))
        if total_weeks:
            design = max(total_weeks // 3, 1)
            delivery = max(total_weeks // 2, 1)
            works = max(total_weeks // 4, 1)
            hand = 1
            sched = [
                ("Detailed Design", design),
                ("Materials Order and Delivery", delivery),
                ("Construction Works", works),
                ("Handing over", hand),
            ]
            total = design + delivery + works + hand
        else:
            sched = [
                ("Detailed Design", 1),
                ("Materials Order and Delivery", 8),
                ("Construction Works", 2),
                ("Handing over", 1),
            ]
            total = 12
        t3 = doc.add_table(rows=len(sched) + 1, cols=2)
        t3.style = "Table Grid"
        for i, (k, v) in enumerate(sched):
            t3.cell(i, 0).text = k
            t3.cell(i, 1).text = f"{v} Weeks"
            t3.cell(i, 0).paragraphs[0].runs[0].bold = True
        last = t3.cell(len(sched), 0)
        last.text = "Total"
        last.paragraphs[0].runs[0].bold = True
        t3.cell(len(sched), 1).text = f"{total} Weeks"

        for section in doc.sections:
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        out_dir = project_dir(project.pr_number, "deliverables")
        out = out_dir / f"{project.pr_number} Project Summary.docx"
        doc.save(out)
        return out
    finally:
        if own_db:
            db.close()
