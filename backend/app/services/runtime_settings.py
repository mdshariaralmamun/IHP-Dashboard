"""Runtime settings overrides shared by the settings router and consumers.

Admins can override individual keys at runtime via /api/admin/settings. The
overrides live in `data/settings.json` (a single small JSON file) and are
merged on top of the env-driven Settings at read time.

Consumers (e.g. the MTO budget generator reading VAT_RATE / USD_SAR_RATE)
use `effective()` here so there is exactly one place that resolves
"env default + admin override".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import get_settings

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _overrides_path() -> Path:
    # Honour DATA_DIR from the env-driven settings (tests point it at a
    # temp dir) but resolve once per call — cheap and always current.
    return Path(get_settings().DATA_DIR) / "settings.json"


def read_overrides() -> dict[str, Any]:
    path = _overrides_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_overrides(data: dict[str, Any]) -> None:
    path = _overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def effective(key: str, env_default: Any) -> Any:
    """Resolve a setting: admin override if present, else the env default."""
    overrides = read_overrides()
    value = overrides.get(key)
    return env_default if value in (None, "") else value


def project_variables() -> dict[str, Any]:
    """The tunable project variables used by budget/BOQ generation.

    VAT rate and the SAR→USD peg are KAUST standards but admins may adjust
    them at runtime; every consumer reads them through this helper.
    """
    overrides = read_overrides()
    s = get_settings()
    return {
        "VAT_RATE": float(overrides.get("VAT_RATE") or 0.15),
        "USD_SAR_RATE": float(overrides.get("USD_SAR_RATE") or 3.75),
        "DEFAULT_CURRENCY": overrides.get("DEFAULT_CURRENCY") or "SAR",
    }
