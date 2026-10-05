"""Generate the project documents from the tagged KAUST templates.

The team's own templates (see scripts/tag_ihp_templates.py) carry the layout,
fonts and standard clauses; this module fills them from the register and the
AI brief of the PR data room:

    project_summary_template.docx -> Project Summary (EAR / assessment)
    sow_template.docx             -> Scope of Work
    boq_template.xlsx             -> Bill of Quantities / EAR Cost Estimate

Prices are deliberately left blank (the QS owns them); the description, unit
and quantity come from the data room's line items. Anything the data room does
not answer is written as "TBD" so a gap is visible instead of invented.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..models import Project

#: The trades the documents are written in, in the order they appear, with the
#: section letter used by the BOQ.
TRADES: tuple[tuple[str, str, str], ...] = (
    ("A", "Architectural / Civil", "architectural, civil, arch"),
    ("B", "Electrical", "electrical, elec, power"),
    ("C", "Low Current / Telecommunication", "low current, telecommunication, telecom, tgg, it, cctv, data"),
    ("D", "Plumbing", "plumbing, plum, drainage, water, gas, cda, n2"),
    ("E", "HVAC", "hvac, mechanical, exhaust, duct, air"),
    ("F", "Fire Sprinkler System", "fire, sprinkler, vesda"),
)

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _today() -> str:
    today = date.today()
    return f"{today.day} {MONTHS[today.month - 1]} {today.year}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def pr_number(value: str | None) -> str:
    """The bare request number, the way the documents print it.

    The register stores "PR-12592"; the templates print "PR # 12592", so
    prefixing the stored value again produced "PR # PR-12592".
    """
    text = _text(value)
    if text.upper().startswith("PR"):
        text = text[2:]
    return text.lstrip("-_ #")


def trade_for(raw: str | None) -> str:
    """Map a brief's free-text trade onto the document's own trade name."""
    needle = (raw or "").strip().lower()
    if not needle:
        return "General"
    for _letter, name, keys in TRADES:
        if name.lower() in needle or needle in name.lower():
            return name
        for key in keys.split(", "):
            if key and key in needle:
                return name
    return _text(raw) or "General"


def scope_blocks(brief: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The brief's scope-by-trade as document-ready blocks.

    A trade is only written when the brief has something for it: the documents
    say "(Not Seen)" for a trade nobody has assessed, which is exactly how the
    team marks it by hand.
    """
    rows = (brief or {}).get("scope_by_trade") or []
    grouped: dict[str, list[str]] = {}
    notes: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = trade_for(row.get("trade"))
        works = grouped.setdefault(name, [])
        requirement = _text(row.get("requirement"))
        for line in requirement.split("\n"):
            line = line.strip(" \t-•")
            if line:
                works.append(line)
        for extra in row.get("assumptions") or []:
            if _text(extra):
                notes.setdefault(name, []).append(_text(extra))
    blocks = []
    for _letter, name, _keys in TRADES:
        if name in grouped:
            works = grouped.pop(name)
            if notes.get(name):
                works = works + ["Assumption: " + note for note in notes[name]]
            blocks.append({"name": name, "works": works or ["TBD"]})
    for name, works in grouped.items():
        if name == "General":
            continue
        blocks.append({"name": name, "works": works or ["TBD"]})
    return blocks


def _items_by_trade(brief: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in (brief or {}).get("line_items") or []:
        if not isinstance(item, dict):
            continue
        grouped.setdefault(trade_for(item.get("trade")), []).append(item)
    return grouped


def _quantity(value: Any) -> float | str | None:
    text = _text(value)
    if not text:
        return None
    cleaned = text.replace(",", "").replace(" ", "")
    try:
        number = float(cleaned)
    except ValueError:
        return text  # "TBD", "Site measure" - keep the words, never invent
    return int(number) if number == int(number) else number


def site_location(project: Project) -> str:
    """The location exactly the way the team writes it.

    "3-2650" (or "B7 L2 A3") is decoded against the site's own masters and
    printed as "Building 3 Level 2 Area 6 Rm# 3-2650", which is how it appears
    on the drawings and in the O&M tracker. Anything that does not decode is
    passed through untouched - never guessed at.
    """
    raw = (project.location or "").strip()
    if not raw:
        return "TBD"
    try:
        from . import reference

        decoded = reference.decode_location(raw)
    except Exception:  # noqa: BLE001 - the reference masters are optional
        decoded = None
    if not decoded:
        return raw
    parts = [f"Building {decoded.get('building')}"]
    if decoded.get("level") is not None:
        parts.append(f"Level {decoded['level']}")
    if decoded.get("area") is not None:
        parts.append(f"Area {decoded['area']}")
    if decoded.get("room"):
        parts.append(f"Rm# {decoded['room']}")
    return " ".join(parts)


def is_aspec(project: Project) -> bool:
    """An ASEPC request is delivered within the IHP budget, not against a PO."""
    return "asep" in (project.funding_source or "").strip().lower()


def wbs_code(project: Project) -> str:
    """The WBS the summary prints.

    The PR request / master register carries the cost centre (e.g.
    "KCR/1/2601-01-01" for an ASEPC request, "12380" or "BAS/1/1435-01-01" for
    a baseline one). Free text with no number in it is never dressed up as a
    cost centre: it prints TBD.
    """
    for source in (
        getattr(project, "wbs_number", None),
        project.funding_source,
    ):
        text = (source or "").strip()
        if text and any(character.isdigit() for character in text):
            return text
    return "TBD"


def budget_line(project: Project) -> str:
    """The TOTAL ESTIMATED PROJECT COST cell.

    ASEPC: "Within IHP budget". A baseline request carries its own estimate, so
    the number is printed as the dollars the team writes ($ 3,200). When a
    baseline request has no estimate on file the cell says TBD rather than
    claiming a budget nobody approved.
    """
    if is_aspec(project):
        return "Within IHP budget"
    amount = getattr(project, "cost_estimate_usd", None)
    if isinstance(amount, (int, float)) and amount > 0:
        return f"$ {amount:,.0f}"
    generated = cost_estimate_usd(project)
    if generated.startswith("$"):
        return generated
    return "TBD"


def cost_estimate_usd(project: Project) -> str:
    """The USD total of the newest generated Cost Estimate, when there is one.

    The workbook holds formulas (=I*D, then the exchange rate), so it is
    recomputed here from the quantities and unit prices the app itself wrote -
    reading the cells back would need Excel to have saved a cached value.
    """
    import openpyxl

    from ..core.config import get_settings

    directory = Path(get_settings().DATA_DIR) / "projects"
    candidates: list[Path] = []
    if directory.exists():
        for path in directory.rglob("*.xlsx"):
            name = path.name.lower()
            if "cost estimate" in name and name.startswith(project.pr_number.lower()):
                candidates.append(path)
    if not candidates:
        return "TBD"
    newest = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        workbook = openpyxl.load_workbook(newest, data_only=True)
        sheet = workbook["Bill of Quantity"]
        total = 0.0
        for row in range(6, sheet.max_row + 1):
            label = str(sheet.cell(row=row, column=2).value or "").strip().upper()
            if label.startswith("TOTAL"):
                break
            quantity = sheet.cell(row=row, column=4).value
            price = sheet.cell(row=row, column=9).value
            if isinstance(quantity, (int, float)) and isinstance(price, (int, float)):
                total += float(quantity) * float(price)
        workbook.close()
    except Exception:  # noqa: BLE001 - a missing/odd workbook must not break the summary
        return "TBD"
    if total <= 0:
        return "TBD"
    return f"$ {total:,.0f}"


def _intro(project: Project, why: str) -> str:
    where = project.location or "the site"
    return (
        "King Abdullah University of Science & Technology (KAUST) intends to "
        f"{why} at {where}."
    )


# ---------------------------------------------------------------------------
# Word documents
# ---------------------------------------------------------------------------

def summary_context(
    project: Project,
    brief: dict[str, Any] | None,
    derived: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocks = scope_blocks(brief)
    derived = derived or {}
    return {
        "date": _today(),
        "recipient": project.pi_name or "Project Proponent",
        "introduction": _intro(project, "proceed with " + project.title),
        "scope": blocks,
        "project_reference": f"{project.pr_number} {project.title}".strip(),
        "division": _division(project, derived),
        "customer": project.pi_name or "TBD",
        # Contact is the requester's own email (the PI Email column of the
        # master register, which is where the PR request's Requester Email
        # lands); the location is decoded into the site's written form.
        "contact": project.pi_email or "TBD",
        "project_location": site_location(project),
        "budget": budget_line(project),
        "wbs": wbs_code(project),
        "schedule": {
            "detailed_design": "1 Weeks",
            "materials": "8 Weeks",
            "construction": "2 Weeks",
            "handover": "1 Week",
            "total": "12 Weeks",
        },
    }


def sow_context(project: Project, brief: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "introduction": _intro(
            project, "avail the services for " + project.title
        ),
        "scope": scope_blocks(brief),
        "pr_no": pr_number(project.pr_number),
        "ear_no": pr_number(project.ear_number) or "TBD",
        "revision": "1",
        "project_title": project.title,
        "location_line": project.location or "",
    }


def _division(project: Project, derived: dict[str, Any] | None = None) -> str:
    """The division the team files the PR under (from the tracker, else IHP)."""
    for source in (derived or {}, {"division": getattr(project, "division", None)}):
        value = source.get("division")
        if value:
            return str(value)
    return "IHP"


def generate_project_summary(
    project: Project,
    brief: dict[str, Any] | None,
    out_path: Path,
    derived: dict[str, Any] | None = None,
) -> Path:
    from docxtpl import DocxTemplate

    from .docgen import template_path

    template = template_path("project_summary_template.docx")
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    doc = DocxTemplate(str(template))
    doc.render(summary_context(project, brief, derived))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


def generate_sow(project: Project, brief: dict[str, Any] | None, out_path: Path) -> Path:
    from docxtpl import DocxTemplate

    from .docgen import template_path

    template = template_path("sow_template.docx")
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    doc = DocxTemplate(str(template))
    doc.render(sow_context(project, brief))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# BOQ / Cost Estimate workbook
# ---------------------------------------------------------------------------

def generate_boq(
    project: Project,
    brief: dict[str, Any] | None,
    out_path: Path,
    *,
    revision: int = 0,
    vat: float = 0.15,
    fx: float = 3.75,
    title: str = "BILL OF QUANTITIES",
    prices: dict[str, float] | None = None,
) -> Path:
    """Fill the team's own BOQ workbook: identity block, items, totals.

    The layout (cover page, two-tier header, totals block) is the template's;
    only the body is rebuilt. Price cells are left empty on purpose.
    """
    import openpyxl
    from openpyxl.styles import Font

    from .docgen import template_path

    template = template_path("boq_template.xlsx")
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    workbook = openpyxl.load_workbook(template)
    sheet = workbook["Bill of Quantity"]

    # Wipe the example body (keep the header rows 1-5 and the sheet itself).
    for row in sheet.iter_rows(min_row=6, max_row=sheet.max_row, min_col=1, max_col=10):
        for cell in row:
            cell.value = None

    ear = f" / EAR# {pr_number(project.ear_number)}" if project.ear_number else ""
    sheet["A1"] = f"PR # {pr_number(project.pr_number)}{ear}"
    sheet["B1"] = project.title
    sheet["G1"] = "Date:"
    sheet["I1"] = datetime.now().date().isoformat()
    sheet["A2"] = "LOCATION:"
    sheet["B2"] = project.location or ""
    sheet["A3"] = title

    items_by_trade = _items_by_trade(brief)
    row = 6
    first_item_row = None
    last_item_row = None
    for letter, name, _keys in TRADES:
        items = items_by_trade.get(name)
        if not items:
            continue
        sheet.cell(row=row, column=1, value=letter).font = Font(bold=True)
        sheet.cell(row=row, column=2, value=name).font = Font(bold=True)
        row += 1
        for number, item in enumerate(items, start=1):
            if first_item_row is None:
                first_item_row = row
            sheet.cell(row=row, column=1, value=number)
            description = _text(item.get("description"))
            spec = _text(item.get("spec"))
            if spec and spec.lower() not in description.lower():
                description = (description + "\n" + spec).strip()
            sheet.cell(row=row, column=2, value=description or "TBD")
            sheet.cell(row=row, column=3, value=_text(item.get("unit")) or None)
            sheet.cell(row=row, column=4, value=_quantity(item.get("qty")))
            # A price comes from the Planner's price master when the line item
            # matched a row there; otherwise the cell stays empty for the QS.
            key = _text(item.get("ref")) or description
            price = (prices or {}).get(key)
            if price:
                sheet.cell(row=row, column=9, value=float(price))
            sheet.cell(row=row, column=10, value=f"=I{row}*D{row}")
            last_item_row = row
            row += 1
    # Trades the brief never mentioned are still shown as "(Not Seen)".
    for letter, name, _keys in TRADES:
        if name not in items_by_trade:
            sheet.cell(row=row, column=1, value=letter).font = Font(bold=True)
            sheet.cell(row=row, column=2, value=name).font = Font(bold=True)
            sheet.cell(row=row, column=2).font = Font(
                bold=True, italic=True, color="FF999999"
            )
            row += 1
            sheet.cell(row=row, column=2, value="(Not Seen)")
            row += 1

    total_row = row + 1
    span = (
        f"SUM(J{first_item_row}:J{last_item_row})"
        if first_item_row is not None
        else "0"
    )
    labels = (
        ("TOTAL (SAR)", f"={span}"),
        ("TOTAL (USD)", f"=J{total_row}/{fx}"),
        (f"VAT {int(vat * 100)}%", f"=J{total_row}*{vat}"),
        ("TOTAL + VAT (SAR)", f"=J{total_row}+J{total_row + 2}"),
        ("TOTAL + VAT (USD)", f"=J{total_row + 3}/{fx}"),
    )
    for offset, (label, formula) in enumerate(labels):
        target = total_row + offset
        sheet.cell(row=target, column=2, value=label).font = Font(bold=True)
        sheet.cell(row=target, column=10, value=formula)

    cover = workbook["Cover page"]
    request_no = project.pr_number.replace("PR-", "").replace("PR", "").strip()
    cover["I7"] = request_no
    cover["F16"] = f"REVISION-{revision}"
    cover["C22"] = "CONCERNED BUILDING:"
    cover["D12"] = title

    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out_path)
    return out_path


def generate_boq_mto(
    project: Project,
    brief: dict[str, Any] | None,
    out_path: Path,
    *,
    revision: int = 0,
) -> Path:
    """The unpriced materials take-off: same grid, no prices, parent rows."""
    return generate_boq(
        project, brief, out_path, revision=revision, title="MATERIALS TAKEOFF"
    )


def generate_cost_estimate(
    project: Project,
    brief: dict[str, Any] | None,
    out_path: Path,
    *,
    prices: dict[str, float] | None = None,
) -> Path:
    """The EAR Cost Estimate: the BOQ grid with the price master filled in.

    This is the Project Budget step between the MOM and the EAR summary: the
    quantities come from the data room, the rates come from the Planner's
    price master. Lines the master cannot price stay empty for the QS.
    """
    return generate_boq(
        project,
        brief,
        out_path,
        title="EAR COST ESTIMATE",
        prices=prices,
    )


#: Stable key for a line item (the brief's REF, else its description).
def line_key(item: dict[str, Any]) -> str:
    return _text(item.get("ref")) or _text(item.get("description"))
