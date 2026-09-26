"""CLI wrapper: sync the Planner's price-master markdown into master_pricing.

Same logic as POST /api/mto/pricing/sync, runnable without the server:

    cd backend
    python -m scripts.import_price_master [path-to-md]

Path defaults to PRICE_MASTER_PATH (env / .env), which defaults to the
Planner's cost-estimates file on E:.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services import price_master  # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else get_settings().PRICE_MASTER_PATH
    print(f"IHP price-master sync\n  source: {path}\n" + "=" * 50)
    db = SessionLocal()
    try:
        result = price_master.sync_from_file(db, path)
    finally:
        db.close()
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1
    for key, value in result.items():
        if key != "note":
            print(f"  {key:<20} {value}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
