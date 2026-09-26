"""Import MACC price list into IHP master pricing database.

Reads the MACC Excel quotation file and populates the master_pricing table.
Used to suggest unit rates in BOQ/MTO generation for IHP projects.

Usage:
    cd backend
    .venv\Scripts\python.exe -m scripts.import_macc_pricing

Or directly:
    python -m scripts.import_macc_pricing
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `app.*` importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import MasterPricing  # noqa: E402


# ---------------------------------------------------------------------------
# Column positions in the MACC "MACC - Items Price List - Quotation.xlsx"
# Based on the file structure observed (Aug 2025). Adjust if your version
# differs.
# ---------------------------------------------------------------------------

# 1: Item Code (e.g., P-201, M-104)
# 2: Description
# 3: Trade (CIVIL, MECH, ELEC, PLUMB, HVAC, ARCH)
# 4: Unit (L.M., EA, BOX, KG, etc.)
# 5: Unit Rate (SAR)

_MACCOLUMN_ITEM_CODE = 1
_MACCOLUMN_DESCRIPTION = 2
_MACCOLUMN_TRADE = 3
_MACCOLUMN_UNIT = 4
_MACCOLUMN_UNIT_RATE = 5


def normalize_trade(trade_str: str | None) -> str | None:
    """Normalize trade name to IHP internal codes.

    Maps common Excel trade tokens to the IHP TRADE_OPTIONS codes.
    """
    if not trade_str:
        return None
    t = trade_str.strip().upper()
    mapping = {
        "CIVIL": "civil_arch",
        "MECH": "mechanical",
        "ELEC": "electrical",
        "PLUMB": "plumbing",
        "HVAC": "hvac",
        "ARCH": "civil_arch",
        "LIGHT_CURRENT": "low_current",
        "FIRE": "fire_protection",
        "LANDSCAPE": "landscape",
    }
    return mapping.get(t, t.lower())


def import_macc_pricing(xlsx_path: Path | str = None) -> dict:
    """Import pricing from the MACC quotation xlsx into master_pricing.

    Args:
        xlsx_path: Path to the MACC xlsx file. Defaults to
            E:/ENGINEERING_DATA/Trakers/MACC - Items Price List - Quotation.xlsx

    Returns:
        dict with keys 'imported', 'updated', 'skipped', 'errors'
    """
    if xlsx_path is None:
        xlsx_path = Path(
            "E:/ENGINEERING_DATA/Trakers/MACC - Items Price List - Quotation.xlsx"
        )

    if not Path(xlsx_path).exists():
        print(f"ERROR: File not found: {xlsx_path}")
        return {"imported": 0, "updated": 0, "skipped": 0, "errors": 1}

    wb = openpyxl.load_workbook(str(xlsx_path), data_only=True)
    sheet_name = wb.sheetnames[0]  # use first sheet
    ws = wb[sheet_name]

    db = SessionLocal()
    imported = 0
    updated = 0
    skipped = 0
    errors = 0

    print(f"Reading sheet '{sheet_name}' ({ws.max_row} rows x {ws.max_column} cols)")

    for r in range(2, ws.max_row + 1):  # skip header row (row 1)
        try:
            raw_item_code = ws.cell(r, _MACCOLUMN_ITEM_CODE).value
            raw_description = ws.cell(r, _MACCOLUMN_DESCRIPTION).value
            raw_trade = ws.cell(r, _MACCOLUMN_TRADE).value
            raw_unit = ws.cell(r, _MACCOLUMN_UNIT).value
            raw_rate = ws.cell(r, _MACCOLUMN_UNIT_RATE).value

            # Skip if no item code
            if not raw_item_code:
                skipped += 1
                continue

            item_code = str(raw_item_code).strip()
            description = str(raw_description).strip() if raw_description else ""
            trade = normalize_trade(raw_trade)
            unit = str(raw_unit).strip() if raw_unit else "EA"
            # Handle rate: could be int, float, or string
            if raw_rate is None:
                unit_rate = 0.0
            elif isinstance(raw_rate, (int, float)):
                unit_rate = float(raw_rate)
            else:
                try:
                    unit_rate = float(str(raw_rate).replace(",", ""))
                except ValueError:
                    unit_rate = 0.0
                    errors += 1
                    print(
                        f"  ! Row {r}: could not parse rate '{raw_rate}' for {item_code}"
                    )

            # Upsert into master_pricing
            existing = db.scalar(
                select(MasterPricing).where(
                    MasterPricing.item_code == item_code
                )
            )
            if existing:
                # Update existing
                existing.description = description or existing.description
                existing.trade = trade or existing.trade
                existing.unit = unit or existing.unit
                existing.base_unit_rate = unit_rate
                existing.last_updated = datetime.utcnow()
                updated += 1
            else:
                # Insert new
                db.add(
                    MasterPricing(
                        item_code=item_code,
                        description=description,
                        trade=trade,
                        unit=unit,
                        base_unit_rate=unit_rate,
                        currency="SAR",
                    )
                )
                imported += 1

            skipped += 1  # count every processed row as "handled"

        except Exception as e:
            errors += 1
            print(f"  ! Error row {r}: {e}")
            continue

    db.commit()
    db.close()

    result = {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
    print("\n" + "=" * 50)
    print(f"Import Summary:")
    print(f"  New items : {imported}")
    print(f"  Updated   : {updated}")
    print(f"  Skipped   : {skipped}")
    print(f"  Errors    : {errors}")
    print("=" * 50)
    return result


def main() -> int:
    """CLI entry point."""
    print("IHP MACC Price List Importer")
    print("=" * 50)
    result = import_macc_pricing()
    print("\nDone. Database updated.")
    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())