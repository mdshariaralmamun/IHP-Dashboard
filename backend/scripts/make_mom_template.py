"""Generate the KAUST MOM template at templates/mom_template.docx.

Reproduces the real KAUST Facilities Management MOM layout (reference:
MOM-PR8662): bordered header block with the KAUST logo, FACILITIES
MANAGEMENT / CLIENT-PROJECT / Minutes of Meeting, form code KA-HBRP-G-MOM
and Revision No.; a 4-column info table (Project Number/Title, Meeting
Title, Meeting Location + Meeting Number, Date + Time); Attendees table;
Agenda / Preliminary Scope of Work table. Body text is Times New Roman,
table content Calibri, matching the reference document.

docxtpl Jinja tags: {{ pr_number }}, {{ title }}, {{ revision_no }},
{{ meeting_title }}, {{ meeting_location }}, {{ meeting_number }},
{{ meeting_date }}, {{ meeting_time }},
{%tr for a in attendees %} with {{ a.name }}/{{ a.title }}/{{ a.email }},
{%tr for item in agenda %} with {{ loop.index }}/{{ item.scope }}/
{{ item.action }}/{{ item.etc }}.

Run from backend/:
    .venv/Scripts/python.exe scripts/make_mom_template.py
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
OUT_PATH = TEMPLATES_DIR / "mom_template.docx"
LOGO_PATH = TEMPLATES_DIR / "kaust_logo.png"

SERIF = "Times New Roman"
SANS = "Calibri"


def _set_font(run, name):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _bold(cell, text, center=False, size=11, font=SERIF):
    cell.text = ""
    p = cell.paragraphs[0]
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(size)
    _set_font(run, font)


def _plain(cell, text, center=False, size=11, font=SERIF):
    cell.text = ""
    p = cell.paragraphs[0]
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.font.size = Pt(size)
    _set_font(run, font)


def _shade(cell, hex_color="D9D9D9"):
    shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {
        qn("w:val"): "clear",
        qn("w:fill"): hex_color,
    })
    cell._tc.get_or_add_tcPr().append(shd)


def _col_widths(table, widths):
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width)


def _cell_margins(table, top=50, bottom=50, left=110, right=110):
    """Padding inside every cell (twips) — the real MOM has airy rows."""
    tbl_pr = table._tbl.tblPr
    mar = tbl_pr.makeelement(qn("w:tblCellMar"), {})
    for side, value in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        mar.append(
            tbl_pr.makeelement(qn(f"w:{side}"), {qn("w:w"): str(value), qn("w:type"): "dxa"})
        )
    tbl_pr.append(mar)


def _row_loop(table, marker_row, content_texts, font=SANS):
    """docxtpl row loop: {%tr %} replaces its ENTIRE row, so the for/endfor
    markers sit alone in their rows with the content row between them."""
    for cell, text in zip(table.rows[marker_row + 1].cells, content_texts):
        _plain(cell, text, font=font)


def main() -> Path:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10)
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.7)
        section.right_margin = Inches(0.7)

    # ---------- header block: university name + logo/FM/form-code table ----------
    head = doc.add_table(rows=4, cols=3)
    head.style = "Table Grid"
    # Row 0: university name across the full width
    name_cell = head.rows[0].cells[0].merge(head.rows[0].cells[2])
    _bold(name_cell, "KING ABDULLAH UNIVERSITY OF SCIENCE AND TECHNOLOGY", center=True, size=13, font=SANS)
    # Logo spans rows 1-3 in column 0
    logo_cell = head.rows[1].cells[0].merge(head.rows[3].cells[0])
    logo_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    logo_par = logo_cell.paragraphs[0]
    logo_par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if LOGO_PATH.exists():
        logo_par.add_run().add_picture(str(LOGO_PATH), width=Inches(1.6))
    # Middle column
    _plain(head.rows[1].cells[1], "FACILITIES MANAGEMENT", center=True, size=11)
    _plain(head.rows[2].cells[1], "CLIENT / PROJECT", center=True, size=11)
    _bold(head.rows[3].cells[1], "Minutes of Meeting", center=True, size=11)
    # Right column
    _plain(head.rows[1].cells[2], "KA-HBRP-G-MOM", center=True, size=11)
    _plain(head.rows[2].cells[2], "", center=True)
    _plain(head.rows[3].cells[2], "Revision No.: {{ revision_no }}", center=True, size=11)
    _col_widths(head, (2.2, 3.4, 1.5))
    _cell_margins(head, top=30, bottom=30)

    doc.add_paragraph("")

    # ---------- info table ----------
    info = doc.add_table(rows=4, cols=4)
    info.style = "Table Grid"
    proj_label = info.rows[0].cells[0]
    _plain(proj_label, "Project Number/Title")
    _shade(proj_label)
    proj_value = info.rows[0].cells[1].merge(info.rows[0].cells[3])
    _plain(proj_value, "{{ pr_number }} {{ title }}")

    _bold(info.rows[1].cells[0], "Meeting Title")
    title_value = info.rows[1].cells[1].merge(info.rows[1].cells[3])
    _plain(title_value, "{{ meeting_title }}")

    _bold(info.rows[2].cells[0], "Meeting Location")
    _plain(info.rows[2].cells[1], "{{ meeting_location }}")
    _plain(info.rows[2].cells[2], "Meeting Number")
    _plain(info.rows[2].cells[3], "{{ meeting_number }}")

    _bold(info.rows[3].cells[0], "Date")
    _plain(info.rows[3].cells[1], "{{ meeting_date }}")
    _plain(info.rows[3].cells[2], "Time")
    _plain(info.rows[3].cells[3], "{{ meeting_time }}")
    _col_widths(info, (1.55, 2.6, 1.55, 1.4))
    _cell_margins(info)

    # ---------- attendees ----------
    att_label = doc.add_paragraph()
    att_run = att_label.add_run("Attendees:")
    att_run.bold = True
    _set_font(att_run, SERIF)
    attendees = doc.add_table(rows=4, cols=3)
    attendees.style = "Table Grid"
    for cell, label in zip(attendees.rows[0].cells, ("Name", "Title", "Email")):
        _bold(cell, label, center=True, font=SANS)
    attendees.rows[1].cells[0].text = "{%tr for a in attendees %}"
    _row_loop(attendees, 1, ("{{ a.name }}", "{{ a.title }}", "{{ a.email }}"))
    attendees.rows[3].cells[0].text = "{%tr endfor %}"
    _col_widths(attendees, (2.0, 3.3, 1.8))
    _cell_margins(attendees)

    # ---------- agenda ----------
    ag_label = doc.add_paragraph()
    ag_run = ag_label.add_run("Agenda:")
    ag_run.bold = True
    _set_font(ag_run, SERIF)
    agenda = doc.add_table(rows=4, cols=4)
    agenda.style = "Table Grid"
    for cell, label in zip(
        agenda.rows[0].cells, ("#", "Preliminary Scope of Work", "Action/Action by", "ETC")
    ):
        _bold(cell, label, center=True, font=SANS)
    agenda.rows[1].cells[0].text = "{%tr for item in agenda %}"
    _row_loop(
        agenda, 1, ("{{ loop.index }}", "{{ item.scope }}", "{{ item.action }}", "{{ item.etc }}")
    )
    agenda.rows[3].cells[0].text = "{%tr endfor %}"
    _col_widths(agenda, (0.35, 4.35, 1.5, 0.9))
    _cell_margins(agenda)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT_PATH))
    return OUT_PATH


if __name__ == "__main__":
    path = main()
    print(f"Wrote {path}")
