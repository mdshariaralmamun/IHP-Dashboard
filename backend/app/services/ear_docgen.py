"""EAR document generation stub (v2 Section 7 UI work covers the full
template; for now we emit a placeholder .docx so the endpoint contract
is satisfied and the build stays green).
"""

from __future__ import annotations

from pathlib import Path

from ..models import EarRecord, Project


def generate_ear_document(
    project: Project, ear: EarRecord, out_path: Path
) -> tuple[str, str]:
    """Render an EAR document. Stub: writes a placeholder text file and
    returns (docx_filename, pdf_filename). The full template lives in the
    Section 7 UI redesign pass.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"EAR for {project.pr_number} — {project.title}\n"
        f"Status: {ear.status}\n"
        f"Version: {ear.version}\n\n"
        f"{ear.summary}\n\n{ear.recommendations}\n",
        encoding="utf-8",
    )
    return out_path.name, None
