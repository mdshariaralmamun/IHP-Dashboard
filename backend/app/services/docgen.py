"""Document generation: docxtpl rendering + optional PDF conversion.

PDF conversion uses LibreOffice (`soffice`) when available on PATH; when it
is absent (e.g. local dev machines), docx_to_pdf returns None and callers
simply record no PDF - tests must not require LibreOffice.
"""

import shutil
import subprocess
from pathlib import Path

from docxtpl import DocxTemplate

from ..core.config import get_settings


def template_path(template_name: str) -> Path:
    return Path(get_settings().TEMPLATES_DIR) / template_name


def render_docx(template_name: str, context: dict, out_path: Path) -> Path:
    """Render a docxtpl template with `context` and save to `out_path`."""
    tpl = template_path(template_name)
    if not tpl.exists():
        raise FileNotFoundError(f"Template not found: {tpl}")
    doc = DocxTemplate(str(tpl))
    doc.render(context)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


def docx_to_pdf(docx_path: Path) -> Path | None:
    """Convert a docx to PDF via headless LibreOffice; None when unavailable."""
    soffice = shutil.which("soffice")
    if not soffice:
        return None
    pdf_path = docx_path.with_suffix(".pdf")
    try:
        subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except Exception:
        return None
    return pdf_path if pdf_path.exists() else None
