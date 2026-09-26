"""Per-project, per-stage versioned file storage.

Layout: {DATA_DIR}/projects/{pr_number}/{stage}/v{n}_{filename}
where n increments per filename within the stage directory.
"""

import re
from pathlib import Path

from ..core.config import get_settings

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    """Filesystem-safe version of a name (keeps alphanumerics, . _ -)."""
    cleaned = _SAFE_CHARS.sub("_", name).strip("._")
    return cleaned or "file"


def project_dir(pr_number: str, stage: str | None = None) -> Path:
    base = Path(get_settings().DATA_DIR) / "projects" / safe_name(pr_number)
    return base / safe_name(stage) if stage else base


def next_version(directory: Path, filename: str) -> int:
    """Next version number for `filename` in `directory` (1 if never stored)."""
    if not directory.exists():
        return 1
    prefix = f"_{safe_name(filename)}"
    versions = []
    for path in directory.glob(f"v*{prefix}"):
        stem = path.name.split("_", 1)[0]  # "v3"
        try:
            versions.append(int(stem[1:]))
        except ValueError:
            continue
    return max(versions, default=0) + 1


def store_upload(
    pr_number: str, stage: str, filename: str, data: bytes
) -> tuple[Path, int]:
    """Write an upload to its next versioned path. Returns (path, version)."""
    directory = project_dir(pr_number, stage)
    directory.mkdir(parents=True, exist_ok=True)
    version = next_version(directory, filename)
    out_path = directory / f"v{version}_{safe_name(filename)}"
    out_path.write_bytes(data)
    return out_path, version
