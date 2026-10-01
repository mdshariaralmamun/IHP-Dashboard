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


def html_to_pdf(html: str, out_path: Path, *, base_url: str = "") -> Path | None:
    """Render an HTML document to PDF with headless Chromium.

    Chromium rather than LibreOffice on purpose: LibreOffice's HTML import
    ignores the stylesheet, so the styled minute came out black-and-white with
    no logo and a broken table layout. The browser prints exactly what the web
    view shows, including the @media print rules the template carries.

    Returns None when Chromium is unavailable, so the feature degrades instead
    of breaking the download.
    """
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Written next to the output so a relative asset would still resolve; the
    # logo is an absolute URL built from base_url.
    source = out_path.with_suffix(".html")
    source.write_text(html, encoding="utf-8")
    try:
        subprocess.run(
            [
                chromium,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_path}",
                source.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except Exception:
        return None
    finally:
        source.unlink(missing_ok=True)
    return out_path if out_path.exists() else None


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
