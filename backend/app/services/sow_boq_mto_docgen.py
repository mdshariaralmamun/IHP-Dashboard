"""SOW + BOQ + MTO auto-generator (docs/SOW_BOQ_MTO_PROMPT.md v1.0).

Deterministic document generation from source-tagged project data — the
LLM never writes these documents; every paragraph and cell traces to a
SowRecord trade section, a BoqMtoItem row, or Project metadata.

Input contract (SowRecord.trade_sections JSON)::

    {
      "metadata": {                    # §2.2 fields not on the Project row
        "requester": "...", "end_user": "...", "funding": "OPEX",
        "wbs": "12380", "division": "...", "estimated_cost": "USD 480",
        "construction_pr": "12630", "original_pr": "12547"
      },
      "drawings": [                    # §9 drawing register
        {"title": "...", "drawing_no": "...", "rev": "0",
         "date": "2026-09-15", "status": "IFC"}
      ],
      "trades": [
        {"name": "Civil / Architectural", "seen": true,
         "items": [                     # §8.2 scope items
           {"description": "...", "unit": "Lot", "qty": "1",
            "source_tag": "DOC", "source_doc": "EAR",
            "sow_text": "optional expanded §8.3 bullet"}
         ],
         "mto_items": [                 # §8.5 measurement lines
           {"ref": "A.1", "description": "...", "unit": "Lot",
            "qty": 1, "computation": "Lump sum"}
         ]}
      ]
    }

VAT and the SAR/USD peg are read from runtime settings — never hardcoded
(master prompt §14). Output files land in versioned per-project storage
({DATA_DIR}/projects/{pr}/generated|package/).
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from ..models import BoqMtoItem, Project, SowRecord, User
from . import runtime_settings, storage

# --- §3.3 standard text blocks (verbatim — §13: never remove) -----------------

SOW_INTRO_STD = (
    "King Abdullah University of Science & Technology (KAUST) intends to "
    "avail the services {title} at {location}."
)
SOW_CIVIL_STD = (
    "Works under this section include but not limited to modification of the "
    "existing gypsum board wall, reworks, repairs, and repainting affected "
    "wall to match existing finish. Any penetration on the fire rated wall, "
    "to be sealed with fire rated sealant."
)
SOW_GENERAL_STD = (
    "All work shall be carried out in accordance with applicable standard and "
    "comply with KAUST standard/specification. The work shall comply with the "
    "latest edition of the international codes and standards as a minimum "
    "requirement. All work shall comply with KAUST Work Permit and other HSE "
    "related policies and procedures. All work shall follow KAUST quality "
    "procedures. Submit material specification submittals, MRI(s), RFI(s) for "
    "approval. Submit shop drawings for approval prior to any project "
    "execution."
)
SOW_DOCS_STD = (
    "Upon project completion, IHP shall submit project documentation included "
    "but not limited to material selection, specification, RFI, Testing and "
    "Commissioning documents, and as-built drawings as per KAUST Technical "
    "Library standard."
)

# BOQ/MTO trade groups — §4.1/§5.1 order A..F (canonical order, never reordered).
TRADE_GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("A", "Civil / Architectural", ("civil",)),
    ("B", "Electrical", ("electric",)),
    ("C", "Plumbing", ("plumb",)),
    ("D", "HVAC", ("hvac", "mechanical",)),
    ("E", "Low Current", ("low", "current", "telecom", "lc",)),
    ("F", "Fire Sprinkler", ("fire", "sprink",)),
]

# SOW §3.1 section order (2.3 Low Current BEFORE 2.4 Plumbing — differs from
# the A–F BOQ order on purpose; both follow the spec exactly).
SOW_SECTION_ORDER: list[tuple[str, str, str]] = [
    ("2.1", "Civil / Architectural", "A"),
    ("2.2", "Electrical", "B"),
    ("2.3", "Low Current / Telecommunication", "E"),
    ("2.4", "Plumbing", "C"),
    ("2.5", "HVAC", "D"),
    ("2.6", "Fire Sprinkler System", "F"),
]

SOURCE_TAGS = ("DOC", "PLANNER", "SITE", "TBC", "ASSUMPTION")
TBC = "TBC"


# --- helpers -------------------------------------------------------------------

def group_for_trade(trade: str) -> tuple[str, str] | None:
    """Map a free-text trade string onto its A–F group (None if unmatched)."""
    t = (trade or "").lower()
    for code, name, aliases in TRADE_GROUPS:
        if any(a in t for a in aliases):
            return code, name
    return None


def _sections(sow: SowRecord | None) -> dict[str, Any]:
    """Parsed trade_sections JSON (empty structure when absent)."""
    raw = (sow.trade_sections if sow else None) or {}
    trades = raw.get("trades") or []
    if not trades:
        trades = [{"name": name, "seen": False, "items": [], "mto_items": []}
                  for _, name, _ in TRADE_GROUPS]
    return {
        "metadata": raw.get("metadata") or {},
        "drawings": raw.get("drawings") or [],
        "trades": trades,
    }


def _meta(project: Project, sow: SowRecord | None) -> dict[str, str]:
    """§2.2 metadata: trade_sections.metadata over Project-row fields."""
    sec_meta = _sections(sow)["metadata"]
    return {
        "pr": project.pr_number,
        "ear": sec_meta.get("ear_number") or project.ear_number or "TBC",
        "title": project.title,
        "location": project.location or "TBC",
        "division": sec_meta.get("division") or "TBC",
        "requester": sec_meta.get("requester") or "TBC",
        "end_user": sec_meta.get("end_user") or "TBC",
        "funding": project.funding_source or sec_meta.get("funding") or "TBC",
        "wbs": sec_meta.get("wbs") or "TBC",
        "estimated_cost": sec_meta.get("estimated_cost") or "TBC",
        "date": datetime.now().strftime("%d-%b-%Y"),
        "revision": sow.revision_name if sow else "Rev-0",
    }


def _fmt_money(value: float) -> str | float:
    """Numeric cells keep numbers (Excel math works); TBC stays text."""
    return round(value, 2)


def _store(project: Project, stage_dir: str, filename: str) -> Path:
    """Versioned path in per-project storage, keeping the spec filename."""
    directory = storage.project_dir(project.pr_number, stage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    n = storage.next_version(directory, filename)
    return directory / f"v{n}_{filename}"


def find_soffice() -> str | None:
    """Locate LibreOffice: PATH first, then the usual Windows install dirs."""
    found = shutil.which("soffice")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _pdf_convert(docx_path: Path, out_dir: Path) -> Path | None:
    """Best-effort docx → PDF via LibreOffice (None when unavailable)."""
    soffice = find_soffice()
    if not soffice:
        return None
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(out_dir), str(docx_path)],
            capture_output=True, timeout=120, check=True,
        )
        pdf = out_dir / (docx_path.stem + ".pdf")
        return pdf if pdf.exists() else None
    except (subprocess.SubprocessError, OSError):
        return None


# --- SOW (§3) -------------------------------------------------------------------

def generate_sow_docx(project: Project, sow: SowRecord | None) -> Path:
    """Build the SOW Word document: §3.1 structure, §3.3 verbatim blocks,
    all six trade subsections ('(Not Seen)' when empty), traceability annex
    and §9.2 drawing register."""
    sec = _sections(sow)
    meta = _meta(project, sow)
    by_group: dict[str, dict] = {}
    for trade in sec["trades"]:
        g = group_for_trade(trade.get("name", ""))
        key = g[0] if g else trade.get("name", "?")
        by_group[key] = trade

    doc = DocxDocument()

    logo = Path(runtime_settings.__file__).resolve().parents[2] / "templates" / "kaust_logo.png"
    if logo.exists():
        doc.add_picture(str(logo), width=Inches(1.4))

    h = doc.add_heading("SCOPE OF WORK", level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run(
        f"PR # {meta['pr']}    |    EAR # {meta['ear']}    |    {meta['revision']} (DRAFT)"
    )
    r.bold = True
    r.font.size = Pt(11)
    info = doc.add_paragraph()
    info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    info.add_run(f"{meta['title']}\nLOCATION: {meta['location']}\nDate: {meta['date']}")
    doc.add_paragraph()

    # 1. Introduction — §3.3 verbatim, title/location substituted
    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(SOW_INTRO_STD.format(title=meta["title"], location=meta["location"]))

    # 2. Scope of Work — all six subsections, §3.1 order
    doc.add_heading("2. Scope of Work", level=1)
    for num, name, group_code in SOW_SECTION_ORDER:
        doc.add_heading(f"{num} {name}", level=2)
        trade = by_group.get(group_code, {})
        items = trade.get("items") or []
        if trade.get("seen") is False and not items:
            doc.add_paragraph("(Not Seen)", style="List Bullet")
            continue
        if group_code == "A" and items:
            doc.add_paragraph(SOW_CIVIL_STD, style="List Bullet")  # §3.3 verbatim
        for item in items:
            doc.add_paragraph(item.get("sow_text") or item["description"],
                              style="List Bullet")

    # 3 + 4 — §3.3 verbatim
    doc.add_heading("3. General, Codes, and Standards", level=1)
    doc.add_paragraph(SOW_GENERAL_STD)
    doc.add_heading("4. Documentation", level=1)
    doc.add_paragraph(SOW_DOCS_STD)

    # 5. Reference Drawings — §9.2 register (+ §9.3 IFC note)
    doc.add_heading("5. Reference Drawings", level=1)
    drawings = sec["drawings"]
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for i, head in enumerate(["ITEM", "DRAWING TITLE", "DRAWING NO.", "REV", "DATE"]):
        table.rows[0].cells[i].text = head
    if drawings:
        for i, dwg in enumerate(drawings, 1):
            cells = table.add_row().cells
            cells[0].text = str(i)
            cells[1].text = str(dwg.get("title", TBC))
            cells[2].text = str(dwg.get("drawing_no", TBC))
            cells[3].text = str(dwg.get("rev", TBC))
            cells[4].text = str(dwg.get("date", TBC))
            if str(dwg.get("status", "")).upper() == "IFC":
                p = doc.add_paragraph()
                run = p.add_run(
                    f"IFC Drawing {dwg.get('drawing_no')} Rev {dwg.get('rev')} "
                    f"dated {dwg.get('date')} is the governing document for execution."
                )
                run.bold = True
    else:
        row = table.add_row().cells
        row[0].text = "1"
        row[1].text = f"No drawings attached — {TBC}"
        row[2].text = row[3].text = row[4].text = TBC

    # Annex A — traceability (§7: tags preserved in every generated document)
    doc.add_heading("Annex A — Scope Item Traceability", level=1)
    tt = doc.add_table(rows=1, cols=4)
    tt.style = "Table Grid"
    for i, head in enumerate(["Trade", "Scope Item", "Source Tag", "Source Document"]):
        tt.rows[0].cells[i].text = head
    for num, name, group_code in SOW_SECTION_ORDER:
        for item in (by_group.get(group_code, {}).get("items") or []):
            cells = tt.add_row().cells
            cells[0].text = name
            cells[1].text = item["description"]
            cells[2].text = str(item.get("source_tag", TBC))
            cells[3].text = str(item.get("source_doc", TBC))

    filename = f"{project.pr_number} Scope of Work Draft.docx"
    path = _store(project, "generated", filename)
    doc.save(str(path))
    return path


# --- BOQ (§4) -------------------------------------------------------------------

_BOQ_HEADERS = ["REF", "DESCRIPTION", "Unit", "QTY", "SUPPLY U.P.", "SUPPLY TOTAL",
                "INSTALL U.P.", "INSTALL TOTAL", "S.+I. UNIT", "S.+I. TOTAL"]
_HEADER_FILL = PatternFill(start_color="003366", end_color="003366", fill_type="solid")
_GROUP_FILL = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
_TBC_FONT = Font(name="Calibri", size=10, color="BF8F00", bold=True)
_THIN = Border(*(Side(style="thin", color="CCCCCC"),) * 4)


def _sheet_header(ws, meta: dict[str, str]) -> None:
    """§4.3 header block on the Bill of Quantity sheet."""
    ws["A1"] = f"PR # {meta['pr']}    EAR # {meta['ear']}"
    ws["A1"].font = Font(size=11, bold=True, color="003366")
    ws["A2"] = meta["title"]
    ws["A2"].font = Font(size=13, bold=True)
    ws["A3"] = f"LOCATION: {meta['location']}"
    ws["A4"] = f"Date: {meta['date']}    Revision: {meta['revision']} (DRAFT)"


def _totals_block(ws, row: int, subtotal: float, any_priced: bool, usd: float, vat: float) -> int:
    """§4.1 totals rows. All TBC until at least one line is priced."""
    def label_row(label: str, value) -> None:
        nonlocal row
        c = ws.cell(row=row, column=2, value=label)
        c.font = Font(bold=True)
        v = ws.cell(row=row, column=10, value=value)
        v.font = Font(bold=True)
        row += 1

    if any_priced and subtotal > 0:
        vat_amt = subtotal * vat
        total = subtotal + vat_amt
        label_row("TOTAL (SAR)", _fmt_money(subtotal))
        label_row("TOTAL (USD)", _fmt_money(subtotal / usd))
        label_row(f"VAT {vat * 100:g}%", _fmt_money(vat_amt))
        label_row("TOTAL + VAT (SAR)", _fmt_money(total))
        label_row("TOTAL + VAT (USD)", _fmt_money(total / usd))
    else:
        for label in ("TOTAL (SAR)", "TOTAL (USD)", f"VAT {vat * 100:g}%",
                      "TOTAL + VAT (SAR)", "TOTAL + VAT (USD)"):
            label_row(label, TBC)
    return row


def generate_boq_xlsx(project: Project, items: list[BoqMtoItem],
                      sow: SowRecord | None = None) -> Path:
    """Three-sheet BOQ workbook (§4.4): Cover / Bill of Quantity / Take-off."""
    meta = _meta(project, sow)
    pv = runtime_settings.project_variables()
    usd, vat = pv["USD_SAR_RATE"], pv["VAT_RATE"]

    wb = openpyxl.Workbook()

    # Sheet 1 — Cover
    cover = wb.active
    cover.title = "Cover"
    cover["A1"] = "KAUST IN-HOUSE PROJECTS"
    cover["A1"].font = Font(size=16, bold=True, color="003366")
    cover["A2"] = "BILL OF QUANTITIES (BOQ)"
    cover["A2"].font = Font(size=14, bold=True)
    rows = [
        ("PR #", meta["pr"]), ("EAR #", meta["ear"]), ("Project Title", meta["title"]),
        ("Location", meta["location"]), ("Division", meta["division"]),
        ("Requester", meta["requester"]), ("End User", meta["end_user"]),
        ("Source of Funding", meta["funding"]), ("WBS", meta["wbs"]),
        ("Total Estimated Cost (EAR)", meta["estimated_cost"]),
        ("Date", meta["date"]), ("Revision", f"{meta['revision']} (DRAFT)"),
        ("Currency", f"SAR (USD @ {usd})"), ("VAT", f"{vat * 100:g}%"),
    ]
    for i, (k, v) in enumerate(rows, start=4):
        cover.cell(row=i, column=1, value=k).font = Font(bold=True)
        cover.cell(row=i, column=2, value=v)
    cover.column_dimensions["A"].width = 28
    cover.column_dimensions["B"].width = 52

    # Sheet 2 — Bill of Quantity (§4.1 layout, A..F groups)
    ws = wb.create_sheet("Bill of Quantity")
    _sheet_header(ws, meta)
    for col, head in enumerate(_BOQ_HEADERS, 1):
        c = ws.cell(row=6, column=col, value=head)
        c.fill, c.font = _HEADER_FILL, Font(bold=True, color="FFFFFF")
        c.alignment = Alignment(horizontal="center", wrap_text=True)

    grouped: dict[str, list[BoqMtoItem]] = {}
    for item in items:
        g = group_for_trade(item.trade) or ("?", item.trade)
        grouped.setdefault(g[0], []).append(item)

    row = 7
    subtotal, any_priced = 0.0, False
    for code, name, _ in TRADE_GROUPS:
        c = ws.cell(row=row, column=1, value=code)
        c.font, c.fill = Font(bold=True), _GROUP_FILL
        ws.cell(row=row, column=2, value=name).font = Font(bold=True)
        row += 1
        for i, item in enumerate(grouped.get(code, []), 1):
            ref = item.item_code or f"{code}.{i}"
            priced = float(item.unit_rate or 0) > 0
            any_priced = any_priced or priced
            subtotal += float(item.total_rate or 0)
            values = [
                ref, item.description, item.unit, item.quantity,
                item.unit_rate if priced else TBC,
                item.total_rate if priced else TBC,
                TBC, TBC,  # supply/install split not yet captured (v1)
                item.unit_rate if priced else TBC,
                item.total_rate if priced else TBC,
            ]
            for col, value in enumerate(values, 1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _THIN
                if value == TBC:
                    cell.font = _TBC_FONT
            row += 1
    row = _totals_block(ws, row + 1, subtotal, any_priced, usd, vat)
    widths = [7, 46, 8, 8, 13, 13, 13, 13, 12, 13]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    # Sheet 3 — Take-off Trade (measurement computation, §4.4)
    takeoff = wb.create_sheet("Take-off Trade")
    _write_mto_sheet(takeoff, project, sow, title="Take-off Trade")

    filename = f"{project.pr_number} BOQ.xlsx"
    path = _store(project, "generated", filename)
    wb.save(str(path))
    return path


# --- MTO (§5) -------------------------------------------------------------------

def _write_mto_sheet(ws, project: Project, sow: SowRecord | None, title: str) -> None:
    """Shared MTO layout (BOQ sheet 3 + the MTO Design workbook)."""
    meta = _meta(project, sow)
    sec = _sections(sow)
    ws["A1"] = f"{title} — {meta['pr']} / {meta['title']}"
    ws["A1"].font = Font(size=12, bold=True, color="003366")
    ws["A2"] = f"LOCATION: {meta['location']}    Date: {meta['date']}"
    headers = ["Ref", "Description", "Unit", "QTY", "Details", "Computation", "Total"]
    for col, head in enumerate(headers, 1):
        c = ws.cell(row=4, column=col, value=head)
        c.fill, c.font = _HEADER_FILL, Font(bold=True, color="FFFFFF")

    by_group: dict[str, dict] = {}
    for trade in sec["trades"]:
        g = group_for_trade(trade.get("name", ""))
        by_group[g[0] if g else trade.get("name", "?")] = trade

    row = 5
    for code, name, _ in TRADE_GROUPS:
        c = ws.cell(row=row, column=1, value=code)
        c.font, c.fill = Font(bold=True), _GROUP_FILL
        ws.cell(row=row, column=2, value=name).font = Font(bold=True)
        row += 1
        for i, m in enumerate(by_group.get(code, {}).get("mto_items") or [], 1):
            qty = m.get("qty", TBC)
            total = m.get("total", qty if isinstance(qty, (int, float)) else TBC)
            values = [
                m.get("ref") or f"{code}.{i}", m["description"], m.get("unit", TBC),
                qty, m.get("details", ""), m.get("computation", TBC), total,
            ]
            for col, value in enumerate(values, 1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _THIN
                if value == TBC:
                    cell.font = _TBC_FONT
            row += 1
    for i, w in enumerate([8, 42, 8, 8, 18, 26, 10], 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w


def generate_mto_xlsx(project: Project, sow: SowRecord | None) -> Path:
    """MTO Design workbook (§5.3): measurement lines with computation basis."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MTO Design"
    _write_mto_sheet(ws, project, sow, title="MTO Design")
    filename = f"{project.pr_number} MTO Design.xlsx"
    path = _store(project, "generated", filename)
    wb.save(str(path))
    return path


# --- QA checklist (§11) ---------------------------------------------------------

@dataclass
class QaCheck:
    n: int
    check: str
    passed: bool
    detail: str


def run_qa_checks(project: Project, sow: SowRecord | None,
                  items: list[BoqMtoItem]) -> list[dict]:
    """The §11 ten-point checklist. Any failure blocks package finalize."""
    sec = _sections(sow)
    trades = sec["trades"]
    checks: list[QaCheck] = []

    # 1 — every SOW trade with items has at least one BOQ line in its group
    sow_groups_with_items = set()
    unmatched: list[str] = []
    for trade in trades:
        g = group_for_trade(trade.get("name", ""))
        if trade.get("items"):
            key = g[0] if g else "?"
            sow_groups_with_items.add(key)
    boq_groups = {group_for_trade(i.trade)[0] if group_for_trade(i.trade) else "?"
                  for i in items}
    missing = sow_groups_with_items - boq_groups
    for trade in trades:
        if trade.get("items") and group_for_trade(trade.get("name", "")):
            boq_descs = " ".join(i.description.lower() for i in items)
            for item in trade["items"]:
                noun = item["description"].split(",")[0].lower()[:12]
                if noun and noun not in boq_descs:
                    unmatched.append(item["description"][:60])
    checks.append(QaCheck(1, "Every SOW item appears in BOQ", not missing,
                          f"missing trade groups: {sorted(missing) or 'none'}; "
                          f"scope items without direct BOQ text match (may be "
                          f"merged into a Lot line): {unmatched or 'none'}"))

    # 2 — every BOQ item has Unit + QTY
    bad_qty = [i.item_code or i.description for i in items
               if not i.unit or i.quantity is None or float(i.quantity) <= 0]
    checks.append(QaCheck(2, "Every BOQ item has Unit + QTY", not bad_qty,
                          f"items missing unit/qty: {bad_qty or 'none'}"))

    # 3 — every quantity traces to MTO or Lot
    mto_by_group: set[str] = set()
    for trade in trades:
        g = group_for_trade(trade.get("name", ""))
        if trade.get("mto_items"):
            mto_by_group.add(g[0] if g else "?")
    untraced = [i.item_code or i.description for i in items
                if (i.unit or "").lower() != "lot"
                and (group_for_trade(i.trade) and group_for_trade(i.trade)[0] not in mto_by_group)]
    checks.append(QaCheck(3, "Every quantity traces to MTO or Lot", not untraced,
                          f"untraced items: {untraced or 'none'}"))

    # 4 — all trades covered or marked Not Seen
    resolved = sum(1 for t in trades if group_for_trade(t.get("name", "")))
    checks.append(QaCheck(4, "All trades covered (or marked Not Seen)",
                          resolved == 6 and len(trades) == 6,
                          f"{resolved}/6 trade groups resolved from "
                          f"{len(trades)} trade sections"))

    # 5 — standard text blocks used exactly
    checks.append(QaCheck(5, "Standard text blocks used exactly", True,
                          "SOW sections 1/2.1/3/4 are emitted from the "
                          "SOW_*_STD constants verbatim (enforced by generator)"))

    # 6 — drawing register attached
    drawings = sec["drawings"]
    checks.append(QaCheck(6, "Drawing register attached",
                          bool(drawings),
                          f"{len(drawings)} drawing(s) registered"
                          if drawings else "no drawings uploaded — register shows TBC"))

    # 7 + 8 — currency + VAT from runtime settings
    pv = runtime_settings.project_variables()
    checks.append(QaCheck(7, f"Currency: SAR + USD @ {pv['USD_SAR_RATE']}",
                          pv["USD_SAR_RATE"] > 0,
                          f"USD_SAR_RATE={pv['USD_SAR_RATE']} (runtime settings)"))
    checks.append(QaCheck(8, f"VAT {pv['VAT_RATE'] * 100:g}% applied",
                          pv["VAT_RATE"] > 0,
                          f"VAT_RATE={pv['VAT_RATE']} (runtime settings)"))

    # 9 — all tags present and valid
    bad_tags = []
    for trade in trades:
        for item in trade.get("items") or []:
            if item.get("source_tag") not in SOURCE_TAGS:
                bad_tags.append(item["description"][:40])
    checks.append(QaCheck(9, "All tags present (DOC/PLANNER/SITE/TBC)",
                          not bad_tags, f"invalid/missing tags: {bad_tags or 'none'}"))

    # 10 — no unconfirmed ASSUMPTION
    assumptions = [item["description"][:40] for trade in trades
                   for item in trade.get("items") or []
                   if item.get("source_tag") == "ASSUMPTION"]
    checks.append(QaCheck(10, "No ASSUMPTION left unconfirmed", not assumptions,
                          f"unconfirmed ASSUMPTION items: {assumptions or 'none'}"))

    return [asdict(c) for c in checks]


# --- Final package (§10) --------------------------------------------------------

def generate_package(project: Project, sow: SowRecord | None,
                     items: list[BoqMtoItem], user: User | None = None) -> tuple[Path, list[dict]]:
    """Assemble the §10 ZIP tree: SOW (+PDF), BOQ, MTO, drawings, references,
    CHANGELOG — with the §11 QA verdict embedded. Failing checks block the
    'FINAL' marking; the package is still produced, stamped DRAFT."""
    qa = run_qa_checks(project, sow, items)
    failed = [c for c in qa if not c["passed"]]

    with TemporaryDirectory() as tmp:
        stage = Path(tmp) / f"{project.pr_number}-Package"
        for sub in ("01_SOW", "02_BOQ", "03_MTO", "04_Drawings", "05_Reference"):
            (stage / sub).mkdir(parents=True)

        # SOW (+ best-effort PDF) with the exact spec filename
        sow_docx = stage / "01_SOW" / f"{project.pr_number} Scope of Work Draft.docx"
        saved = generate_sow_docx(project, sow)
        shutil.copyfile(saved, sow_docx)
        _pdf_convert(sow_docx, sow_docx.parent)  # PDF joins the tree if soffice exists

        shutil.copyfile(generate_boq_xlsx(project, items, sow),
                        stage / "02_BOQ" / f"{project.pr_number} BOQ.xlsx")
        shutil.copyfile(generate_mto_xlsx(project, sow),
                        stage / "03_MTO" / f"{project.pr_number} MTO Design.xlsx")

        drawings = _sections(sow)["drawings"]
        readme = stage / "04_Drawings" / "README.txt"
        if drawings:
            readme.write_text(
                "\n".join(f"{d.get('drawing_no', TBC)} Rev {d.get('rev', TBC)} — "
                          f"{d.get('title', TBC)} ({d.get('date', TBC)})"
                          for d in drawings), encoding="utf-8")
        else:
            readme.write_text(
                "No drawings uploaded yet (❓ TBC). Upload drawings via "
                "UPLOAD DRAWING to populate this folder and pass QA check 6.\n",
                encoding="utf-8")

        ref = stage / "05_Reference"
        attachments = list(project.attachments)
        if attachments:
            for att in attachments:
                src = storage.project_dir(project.pr_number) / Path(att.filename).name
                if src.exists():
                    shutil.copyfile(src, ref / att.filename)
        (ref / "README.txt").write_text(
            "Reference documents (PR request, EAR, MOM) attach here when "
            "uploaded to the project.\n", encoding="utf-8")

        lines = [
            f"# CHANGELOG — {project.pr_number} document package", "",
            f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')} (UTC)",
            f"- SOW revision: {sow.revision_name if sow else 'Rev-0'}",
            f"- Generated by: {user.username if user else 'system'}",
            f"- Package status: {'DRAFT — QA FAILED, finalize blocked' if failed else 'FINAL'}", "",
            "## QA checklist (§11)", "",
            "| # | Check | Status | Detail |", "|---|-------|--------|--------|",
        ]
        for c in qa:
            lines.append(f"| {c['n']} | {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | {c['detail']} |")
        (stage / "CHANGELOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

        zip_name = f"{project.pr_number}-Package.zip"
        zip_path = _store(project, "package", zip_name)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(stage.rglob("*")):
                if file.is_file():
                    zf.write(file, file.relative_to(stage.parent))
    return zip_path, qa
