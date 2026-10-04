"""Turn the KAUST IHP Word templates into docxtpl templates.

The team's own templates (E:\\ENGINEERING_DATA\\IHP_Projects\\General
Template- internal\\) carry NO mail-merge fields - they are hand-edited
every time. This script produces the app's tagged copies once:

    Project Summary (PR ----).docx  ->  templates/project_summary_template.docx
    PR XXXX SCOPE -.docx            ->  templates/sow_template.docx

The originals are never touched: they are copied, the example paragraphs are
replaced by Jinja tags (docxtpl), and the file is saved into the app.

Run it from the backend directory whenever the team issues a new template:

    python scripts/tag_ihp_templates.py "E:\\ENGINEERING_DATA\\IHP_Projects\\General Template- internal"

Everything the renderer needs:
  project_summary : date, recipient, introduction, scope[{name, works[]}],
                    project_reference, division, customer, contact,
                    project_location, budget, wbs, schedule.{...}
  sow             : introduction, scope[{name, works[]}], pr_no, ear_no,
                    revision, project_title, location_line
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parents[1]
TEMPLATES = HERE / "templates"


def set_text(paragraph, text: str) -> None:
    """Replace a paragraph's text, keeping its style and formatting.

    Every child except the paragraph properties is removed first: the examples
    put text inside hyperlinks and smart tags, which `paragraph.runs` does not
    see, and leaving those behind appends the old content to the new.
    """
    element = paragraph._p
    for child in list(element):
        if child.tag.endswith("}pPr"):
            continue
        element.remove(child)
    paragraph.add_run(text)


def clear_cell(cell, lines: list[str]) -> None:
    """Replace a whole table cell (merged cells included) with `lines`."""
    paragraphs = list(cell.paragraphs)
    for extra in paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    set_text(cell.paragraphs[0], lines[0] if lines else "")
    for line in lines[1:]:
        cell.add_paragraph(line)


def drop(paragraph) -> None:
    paragraph._element.getparent().remove(paragraph._element)


def tag_project_summary(source: Path, out: Path) -> None:
    shutil.copyfile(source, out)
    doc = Document(out)
    paras = doc.paragraphs

    set_text(paras[0], "Date {{ date }}.")
    set_text(paras[1], "To:  {{ recipient }}")
    set_text(paras[4], "{{ introduction }}")

    # The example trade block (heading + 12 bullets) becomes one loop:
    #   {%p for trade in scope %} / name / {%p for item in trade.items %} /
    #   item / {%p endfor %} / {%p endfor %}
    set_text(paras[7], "{%p for trade in scope %}")
    set_text(paras[8], "{{ trade.name }}")
    paras[8].runs[0].bold = True
    set_text(paras[9], "{%p for item in trade.works %}")
    set_text(paras[10], "{{ item }}")
    set_text(paras[11], "{%p endfor %}")
    set_text(paras[12], "{%p endfor %}")
    for extra in paras[13:20]:
        drop(extra)

    t0 = doc.tables[0]
    clear_cell(t0.cell(0, 1), ["{{ project_reference }}"])
    clear_cell(t0.cell(1, 1), ["{{ division }}"])
    clear_cell(t0.cell(2, 1), ["{{ customer }}"])
    clear_cell(t0.cell(3, 1), ["{{ contact }}"])
    clear_cell(t0.cell(4, 1), ["{{ project_location }}"])

    t1 = doc.tables[1]
    clear_cell(t1.cell(1, 1), ["{{ budget }}"])
    clear_cell(t1.cell(3, 1), ["{{ wbs }}"])

    t2 = doc.tables[2]
    for row, tag in zip(
        range(5), ["detailed_design", "materials", "construction", "handover", "total"]
    ):
        clear_cell(t2.cell(row, 1), ["{{ schedule." + tag + " }}"])

    doc.save(out)


def tag_sow(source: Path, out: Path) -> None:
    shutil.copyfile(source, out)
    doc = Document(out)
    paras = doc.paragraphs

    set_text(paras[1], "{{ introduction }}")
    set_text(paras[4], "{%p for trade in scope %}")
    set_text(paras[5], "{{ trade.name }}")
    paras[5].style = doc.styles["Heading 1"]
    set_text(paras[6], "{%p for item in trade.works %}")
    set_text(paras[7], "{{ item }}")
    paras[7].style = doc.styles["List Paragraph"]
    set_text(paras[8], "{%p endfor %}")
    set_text(paras[9], "{%p endfor %}")
    for extra in paras[10:16]:
        drop(extra)

    table = doc.sections[0].header.tables[0]
    clear_cell(table.cell(1, 0), ["{{ project_title }}"])
    clear_cell(table.cell(2, 1), ["{{ location_line }}"])
    clear_cell(
        table.cell(1, 2),
        ["Rev.-{{ revision }}", "PR # {{ pr_no }}", "EAR# {{ ear_no }}"],
    )
    doc.save(out)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: tag_ihp_templates.py <General Template- internal dir>")
    root = Path(sys.argv[1])
    summary = root / "Template" / "Project Summary" / "Project Summary (PR ----).docx"
    sow = root / "Template" / "DD Tamplate" / "PR XXXX SCOPE -.docx"
    for path in (summary, sow):
        if not path.exists():
            raise SystemExit(f"template not found: {path}")
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    tag_project_summary(summary, TEMPLATES / "project_summary_template.docx")
    tag_sow(sow, TEMPLATES / "sow_template.docx")
    print("tagged:", TEMPLATES / "project_summary_template.docx")
    print("tagged:", TEMPLATES / "sow_template.docx")


if __name__ == "__main__":
    main()
