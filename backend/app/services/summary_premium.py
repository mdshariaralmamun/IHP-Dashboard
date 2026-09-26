"""Project Summary generator - PREMIUM (world-class KAUST edition).

Keeps every field of the official house format, and upgrades the
presentation to engineering-document standards:

  * branded cover block (KAUST | In-House Projects + document control:
    Rev / Date / Prepared / Status),
  * auto-filled project information table (register + O&M location details),
  * executive summary paragraph,
  * scope of work by trade (from the BOQ/MTO items),
  * REFERENCE PROJECTS: similar work from the engineering archive, with the
    documents each predecessor has on file - evidence-based scoping,
  * schedule table + in-document bar chart from the Planner dates,
  * live tracking link (the project's public token) for the PI,
  * footer with PR reference and generation timestamp.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Inches, RGBColor

from ..db import SessionLocal
from ..models import BoqMtoItem, Project
from .storage import project_dir
from .summary_docgen import INTRO, TRADE_ORDER, _match_trade, _weeks_between

KAUST_TEAL = RGBColor(0x00, 0x6A, 0x4E)


def _hdr(doc, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(13)
    r.font.color.rgb = KAUST_TEAL


def _table(doc, rows: list[tuple[str, str]], widths=(2.6, 4.2)) -> None:
    t = doc.add_table(rows=len(rows), cols=2)
    t.style = "Table Grid"
    for i, (k, v) in enumerate(rows):
        c0, c1 = t.cell(i, 0), t.cell(i, 1)
        c0.text = k
        c1.text = str(v)
        c0.paragraphs[0].runs[0].bold = True
    return t


def generate_project_summary_premium(project: Project, context: dict | None = None,
                                     db=None, similar: list[dict] | None = None,
                                     tracking_base_url: str = "") -> Path:
    """World-class KAUST edition of the Project Summary."""
    from ..api.projects import _derive_tracker_fields

    own_db = db is None
    db = db or SessionLocal()
    try:
        d = _derive_tracker_fields(project)
        ctx = context or {}
        pi_name = project.pi_name or ctx.get("pi_name") or "-"
        pi_email = project.pi_email or ctx.get("pi_email") or "-"
        location = project.location or ctx.get("location") or "-"
        loc_details = ctx.get("location_details")
        division = ctx.get("division") or d.get("division") or "-"
        trades = ", ".join(d.get("trades") or []) or "-"
        ptype = d.get("project_type") or "-"

        doc = Document()
        st = doc.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10.5)

        # ---- branded cover -------------------------------------------------
        brand = doc.add_paragraph()
        brand.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = brand.add_run("KAUST  |  In-House Projects (IHP)")
        r.bold = True
        r.font.size = Pt(12)
        r.font.color.rgb = KAUST_TEAL

        title = doc.add_paragraph()
        r = title.add_run("PROJECT SUMMARY")
        r.bold = True
        r.font.size = Pt(22)
        r.font.color.rgb = KAUST_TEAL
        sub = doc.add_paragraph(f"{project.pr_number} - {project.title}")
        sub.runs[0].font.size = Pt(13)

        _table(doc, [
            ("Document No.", f"IHP-PS-{project.pr_number.replace('PR-', '')}-REV0"),
            ("Revision / Date", f"Rev 0  ·  {date.today().strftime('%d %b %Y')}"),
            ("Prepared by", "In-House Projects - Planning"),
            ("Status", "DRAFT for review"),
        ])

        # ---- project information --------------------------------------------
        doc.add_paragraph()
        _hdr(doc, "1. Project Information")
        _table(doc, [
            ("Project Reference", f"{project.pr_number} - {project.title}"),
            ("EAR Number", project.ear_number or "-"),
            ("Division", division),
            ("Customer / Proponent", pi_name),
            ("Contact", pi_email),
            ("Project Location", location + (f" - {loc_details}" if loc_details else "")),
            ("Disciplines", trades),
            ("Project Type / Priority", f"{ptype} / {d.get('priority') or '-'}"),
        ])

        # ---- executive summary ----------------------------------------------
        doc.add_paragraph()
        _hdr(doc, "2. Executive Summary")
        current = d.get("latest_status") or project.stage.replace("_", " ").title()
        doc.add_paragraph(INTRO)
        doc.add_paragraph(
            f"Current status: {current}. The project is tracked in the IHP delivery "
            f"platform under division '{d.get('phase') or '-'}' with a planned finish "
            f"of {d.get('finish_date') or 'to be confirmed'}."
        )

        # ---- scope by trade ---------------------------------------------------
        doc.add_paragraph()
        _hdr(doc, "3. General Scope of Work")
        by_trade: dict[str, list[str]] = {}
        for it in db.query(BoqMtoItem).filter(BoqMtoItem.project_id == project.id).all():
            trade = (it.trade or "General").strip()
            desc = (it.description or "").strip()
            if desc:
                by_trade.setdefault(trade, [])
                if desc not in by_trade[trade]:
                    by_trade[trade].append(desc)
        if not by_trade:
            doc.add_paragraph("(Scope items appear once the BOQ/MTO is prepared.)")
        matched: dict[str, list[str]] = {}
        extra: dict[str, list[str]] = {}
        for trade, lines in by_trade.items():
            label = _match_trade(trade)
            (matched if label else extra).setdefault(label or trade, []).extend(lines)
        for label, _k in TRADE_ORDER:
            lines = matched.get(label)
            if not lines:
                continue
            doc.add_paragraph(label).runs[0].bold = True
            for line in lines[:20]:
                doc.add_paragraph(line, style="List Bullet")
        for trade, lines in extra.items():
            doc.add_paragraph(trade).runs[0].bold = True
            for line in lines[:20]:
                doc.add_paragraph(line, style="List Bullet")

        # ---- reference projects from the archive -------------------------------
        doc.add_paragraph()
        _hdr(doc, "4. Reference Projects (engineering archive)")
        if similar:
            t = doc.add_table(rows=len(similar) + 1, cols=3)
            t.style = "Table Grid"
            for j, h in enumerate(["PR / Title", "Relevance", "Documents on file"]):
                cell = t.cell(0, j)
                cell.text = h
                cell.paragraphs[0].runs[0].bold = True
            for i, hit in enumerate(similar, start=1):
                t.cell(i, 0).text = (
                    f"{hit.get('pr_number')} - {str(hit.get('title'))[:60]}"
                )
                t.cell(i, 1).text = f"{hit.get('score', 0):.0%}"
                t.cell(i, 2).text = ", ".join((hit.get("doc_kinds") or [])[:6]) or "-"
            doc.add_paragraph(
                "Similar past work identified automatically from the IHP engineering "
                "archive; the referenced documents are available from the archive folders.")
        else:
            doc.add_paragraph("No similar past projects found in the archive index.")

        # ---- schedule ------------------------------------------------------------
        doc.add_paragraph()
        _hdr(doc, "5. Indicative Schedule")
        total_weeks = _weeks_between(d.get("start_date"), d.get("finish_date"))
        if total_weeks:
            design = max(total_weeks // 3, 1)
            delivery = max(total_weeks // 2, 1)
            works = max(total_weeks // 4, 1)
            hand = 1
            total = design + delivery + works + hand
        else:
            design, delivery, works, hand, total = 1, 8, 2, 1, 12
        rows = [
            ("Detailed Design", design),
            ("Materials Order and Delivery", delivery),
            ("Construction Works", works),
            ("Handing over", hand),
        ]
        _table(doc, [(k, f"{v} Weeks") for k, v in rows] + [("Total", f"{total} Weeks")])
        # In-document bars: each week = one filled block character.
        doc.add_paragraph()
        for k, v in rows:
            p = doc.add_paragraph()
            r = p.add_run(f"{k:<34} ")
            r.font.name = "Consolas"
            bar = p.add_run("\u2588" * v + "\u2591" * max(total - v, 0))
            bar.font.name = "Consolas"
            bar.font.color.rgb = KAUST_TEAL
            p.add_run(f"  {v}w")

        # ---- commercial -------------------------------------------------------------
        doc.add_paragraph()
        _hdr(doc, "6. Commercial")
        _table(doc, [
            ("Scope", "Attached"),
            ("Total Estimated Project Cost", "Within IHP budget"),
            ("WBS", "-"),
        ])

        # ---- live tracking -------------------------------------------------------------
        if project.tracking_token and tracking_base_url:
            doc.add_paragraph()
            _hdr(doc, "Live Tracking")
            doc.add_paragraph(
                f"Track this project in real time: {tracking_base_url}/track/{project.tracking_token}"
            )

        # ---- footer ----------------------------------------------------------------------
        for section in doc.sections:
            section.left_margin = Inches(0.9)
            section.right_margin = Inches(0.9)
            f = section.footer.paragraphs[0]
            f.text = (
                f"{project.pr_number} Project Summary  ·  Rev 0  ·  "
                f"generated {datetime.now().strftime('%d %b %Y %H:%M')} by IHP platform"
            )
            f.alignment = WD_ALIGN_PARAGRAPH.CENTER
            f.runs[0].font.size = Pt(8)

        out_dir = project_dir(project.pr_number, "deliverables")
        out = out_dir / f"{project.pr_number} Project Summary (KAUST Premium).docx"
        doc.save(out)
        return out
    finally:
        if own_db:
            db.close()
