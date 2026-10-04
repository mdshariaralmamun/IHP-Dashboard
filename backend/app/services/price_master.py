"""Materials price-master sync (Planner's cost-estimates markdown file).

Source of truth: the Planner's frequently-updated price list, currently
``E:\\ENGINEERING_DATA\\trackers\\IHP - Cost Estimates file -1.md`` — a
markdown table exported from Excel with columns:

    REF | DESCRIPTION | Unit | QTY | ITEM PRICE | TOTAL

Only REF / DESCRIPTION / Unit / ITEM PRICE are master data (QTY/TOTAL are
project-specific and ignored). Rows are upserted into ``master_pricing``
keyed by ``item_code = str(REF)`` — the same key the budget generator
matches BOQ items on. Only rows this module previously imported (marker
in ``notes``) are ever updated or deactivated, so MACC-imported rows and
manual entries are never touched.

Trade is inferred from the description (the file has no trade column);
it powers the optional ``/api/mto/pricing?trade=`` filter only. Inferred
trades are flagged in ``notes`` — never promoted to confirmed data.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MasterPricing

#: Marker written to MasterPricing.notes; scopes which rows this module owns.
NOTES_MARKER = "price-master:"

#: Ordered keyword classifier: first match wins (specific before generic).
_TRADE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("low_current", ("cat6", "cat 6", "rj45", "rj 45", "modular jack",
                     "faceplate", "face plate", "data socket", "utp",
                     "systimax", "duplex data")),
    ("fire_protection", ("firestop", "fire stop", "fire rated", "fire sealant",
                         "cp 653", "cp 601", "speed sleeve")),
    ("hvac", ("duct", "damper", "air register", "air balancing", "snorkel",
              "strip curtain", "volume control", "grille", "flanged 316")),
    ("plumbing", ("pp-r", "ppr", "ppfr", "copper", "mueller", "muller",
                  "ball valve", "water filter", "pentair", "festo",
                  "pneumatic", "tubing", "hose", "drain", "p trap", "nibco",
                  "dielectric", "strainer", "jubli", "jubilee", "stauff",
                  "reducing tee", "nipple", "pipe clamp", "crane d")),
    ("electrical", ("emt", "conduit", "socket", "breaker", "mcb", "rcd",
                    "thhn", "wire", "cable", "lug", "junction box",
                    "trunking", "busbar", "grounding", "gland", "din rail",
                    "gewiss", "legrand", "belden", "gfci", "residual",
                    "switch", "label printer")),
    ("civil_arch", ("gypsum", "paint", "putty", "sand paper", "door",
                    "blackout film", "floor coating", "wall", "hacksaw",
                    "masking tape", "roller", "screw", "anchor", "fischer",
                    "channel", "unistrut", "strut", "threaded rod",
                    "crane", "rigger", "riggar", "work permit", "coring")),
]

_ROW_RE = re.compile(r"^\|")
_CELL_SPLIT = re.compile(r"\s*\|\s*")


def infer_trade(description: str) -> str | None:
    """Keyword classifier for the trade column (heuristic, filter-only)."""
    d = (description or "").lower()
    for trade, keywords in _TRADE_KEYWORDS:
        if any(k in d for k in keywords):
            return trade
    return None


def parse_markdown_table(path: Path | str) -> list[dict]:
    """Parse the cost-estimates markdown table into row dicts.

    Skips the banner row, the ``---`` separator, and the header row;
    then takes every well-formed data row with an integer REF and a
    numeric ITEM PRICE.
    """
    rows: list[dict] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in _CELL_SPLIT.split(line.strip("|"))]
        if len(cells) < 6:
            continue
        ref, description, unit, _qty, item_price, _total = cells[:6]
        if not re.fullmatch(r"\d+", ref):
            continue  # banner / separator / header / malformed
        try:
            price = float(item_price.replace(",", ""))
        except ValueError:
            continue
        if price < 0:
            continue
        rows.append({
            "ref": ref,
            "description": description,
            "unit": unit or "EA",
            "item_price": price,
        })
    return rows


def sync_from_file(db: Session, path: Path | str) -> dict:
    """Upsert the file's rows into master_pricing (source-scoped).

    New REFs are inserted; existing price-master rows are updated (price,
    description, unit); rows this module previously imported but that no
    longer exist in the file are deactivated (never deleted — pricing
    history stays queryable). MACC/manual rows are never touched.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {"error": f"price master file not found: {file_path}"}

    rows = parse_markdown_table(file_path)
    marker = f"{NOTES_MARKER}{file_path.name}"
    now = datetime.now(timezone.utc)

    existing = db.scalars(
        select(MasterPricing).where(MasterPricing.notes.like(f"{NOTES_MARKER}%"))
    ).all()
    by_code = {p.item_code: p for p in existing}

    imported = updated = 0
    seen: set[str] = set()
    for row in rows:
        seen.add(row["ref"])
        current = by_code.get(row["ref"])
        trade = infer_trade(row["description"])
        if current is not None:
            current.description = row["description"]
            current.unit = row["unit"]
            current.base_unit_rate = row["item_price"]
            current.trade = trade
            current.notes = marker
            current.is_active = True
            current.last_updated = now
            updated += 1
        else:
            db.add(MasterPricing(
                item_code=row["ref"],
                description=row["description"],
                trade=trade,
                unit=row["unit"],
                base_unit_rate=row["item_price"],
                currency="SAR",
                notes=marker,
            ))
            imported += 1

    # Only rows THIS list previously imported may be retired: a second price
    # list (the store's quotation export) must never deactivate the Planner's
    # own estimates, and vice versa.
    deactivated = 0
    for code, pricing in by_code.items():
        if code in seen or not pricing.is_active:
            continue
        if (pricing.notes or "") != marker:
            continue
        pricing.is_active = False
        pricing.last_updated = now
        deactivated += 1

    db.commit()
    return {
        "source": str(file_path),
        "file_rows": len(rows),
        "imported": imported,
        "updated": updated,
        "deactivated": deactivated,
        "active_master_items": len(
            db.scalars(
                select(MasterPricing).where(MasterPricing.is_active.is_(True))
            ).all()
        ),
        "synced_at": now.isoformat(timespec="seconds"),
        "note": "trade values are keyword-inferred (the file has no trade "
                "column) and are used only for filtering",
    }


def parse_xlsx_table(path: Path | str) -> list[dict]:
    """Read a priced workbook (BOQ / quotation) with openpyxl.

    Accepts any sheet whose header row names a REF / DESCRIPTION / Unit and a
    price column, because the team's quotations come from several suppliers
    and none of them share a layout. Returns the same shape as
    parse_markdown_table: [{ref, description, unit, item_price, total}].
    """
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[dict] = []
    seen_codes: set[str] = set()
    try:
        for sheet in workbook.worksheets:
            header_row = None
            columns: dict[str, int] = {}
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = ["" if v is None else str(v).strip() for v in row]
                lowered = [c.lower() for c in cells]
                if header_row is None:
                    # Several price lists land here: the Planner's export
                    # (REF / DESCRIPTION / Unit / ITEM PRICE) and the store's
                    # quotation export (Item Code / Item Name / Standard Cost /
                    # Supplier). Recognise both rather than make the team
                    # reformat a file they already have.
                    ref = next(
                        (i for i, c in enumerate(lowered)
                         if c in ("ref", "ref.", "item code", "stock number", "item", "no", "id")),
                        None,
                    )
                    desc = next(
                        (i for i, c in enumerate(lowered)
                         if c.startswith("description") or c in ("desc", "item description", "item name")),
                        None,
                    )
                    price = next(
                        (i for i, c in enumerate(lowered)
                         if c in ("item price", "unit price", "u.p.", "rate", "price",
                                  "standard cost", "list price")),
                        None,
                    )
                    if ref is not None and desc is not None and price is not None:
                        header_row = row_index
                        # A supplier's item list numbers its own rows, which
                        # collide with the Planner's REFs (both start at 1):
                        # prefix those so one list never overwrites the other.
                        layout_prefix = (
                            "SUP-" if lowered[desc].startswith("item name") else ""
                        )
                        columns = {
                            "ref": ref,
                            "description": desc,
                            "unit": next(
                                (i for i, c in enumerate(lowered)
                                 if c in ("unit", "u", "uom", "u.m", "quantity per unit")),
                                -1,
                            ),
                            "price": price,
                            "total": next(
                                (i for i, c in enumerate(lowered) if c in ("total", "amount", "extended")),
                                -1,
                            ),
                            "supplier": next(
                                (i for i, c in enumerate(lowered)
                                 if c in ("supplier ids", "supplier", "vendor", "supplier name")),
                                -1,
                            ),
                        }
                    continue
                ref = cells[columns["ref"]] if columns["ref"] < len(cells) else ""
                description = cells[columns["description"]] if columns["description"] < len(cells) else ""
                if not description:
                    continue
                try:
                    price = float(str(cells[columns["price"]]).replace(",", ""))
                except (ValueError, IndexError):
                    price = 0.0
                unit = ""
                if columns["unit"] >= 0 and columns["unit"] < len(cells):
                    unit = cells[columns["unit"]] or "EA"
                supplier = ""
                supplier_index = columns.get("supplier", -1)
                if supplier_index >= 0 and supplier_index < len(cells):
                    supplier = cells[supplier_index]
                # The store's export repeats one quotation id on every line:
                # a non-unique code would collapse the whole list into one
                # row, so anything repeated gets the row number appended.
                code = (layout_prefix + (ref or description[:40])).strip()
                if code in seen_codes:
                    code = f"{code}-{row_index}"
                seen_codes.add(code)
                out.append(
                    {
                        "ref": code,
                        "description": description,
                        "unit": unit or "EA",
                        "item_price": price,
                        "total": 0.0,
                        "supplier": supplier,
                    }
                )
            if out:
                break
    finally:
        workbook.close()
    return out


def sync_rows(db: Session, rows: list[dict], source: str) -> dict:
    """Upsert parsed rows into master_pricing, scoped to `source`."""
    marker = f"{NOTES_MARKER}{source}"
    now = datetime.now(timezone.utc)
    existing = db.scalars(
        select(MasterPricing).where(MasterPricing.notes.like(f"{NOTES_MARKER}%"))
    ).all()
    by_code = {p.item_code: p for p in existing}
    imported = updated = 0
    seen: set[str] = set()
    for row in rows:
        code = str(row["ref"]).strip()
        if not code:
            continue
        seen.add(code)
        trade = infer_trade(row["description"])
        supplier = str(row.get("supplier") or "").strip() or None
        current = by_code.get(code)
        if current is not None:
            current.description = row["description"]
            current.unit = row["unit"]
            current.base_unit_rate = row["item_price"]
            current.trade = trade
            current.notes = marker
            if supplier:
                current.supplier = supplier[:200]
            current.is_active = True
            current.last_updated = now
            updated += 1
        else:
            db.add(
                MasterPricing(
                    item_code=code,
                    description=row["description"],
                    trade=trade,
                    unit=row["unit"],
                    base_unit_rate=row["item_price"],
                    currency="SAR",
                    notes=marker,
                    supplier=supplier[:200] if supplier else None,
                )
            )
            imported += 1
    # Only rows THIS list previously imported may be retired: a second price
    # list (the store's quotation export) must never deactivate the Planner's
    # own estimates, and vice versa.
    deactivated = 0
    for code, pricing in by_code.items():
        if code in seen or not pricing.is_active:
            continue
        if (pricing.notes or "") != marker:
            continue
        pricing.is_active = False
        pricing.last_updated = now
        deactivated += 1
    db.commit()
    return {
        "source": source,
        "file_rows": len(rows),
        "imported": imported,
        "updated": updated,
        "deactivated": deactivated,
    }


#: Words that carry no pricing signal when matching a line item to the master.
_STOPWORDS = frozenset(
    "and or the of for with to a an in on at per as by supply install "
    "installation complete including all necessary accessories new existing "
    "nos no ea lot lm m2 unit".split()
)


def _tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return {t for t in cleaned.split() if t and t not in _STOPWORDS and len(t) > 2}


def suggest_price(db: Session, description: str, unit: str | None = None) -> dict | None:
    """The closest price-master row for a line item, or None.

    Scored on description-token overlap (the master is keyed by REF, but a
    brief's line items rarely carry the Planner's REF), with a unit bonus so
    an "EA" is never priced from an "L.M." line. Only a clear winner is
    returned: a weak match would put a wrong number in front of the QS.
    """
    wanted = _tokens(description)
    if not wanted:
        return None
    candidates = db.scalars(
        select(MasterPricing).where(MasterPricing.is_active.is_(True))
    ).all()
    best: tuple[float, str, MasterPricing] | None = None
    for row in candidates:
        have = _tokens(row.description)
        if not have:
            continue
        overlap = len(wanted & have)
        if overlap == 0:
            continue
        score = overlap / max(len(wanted), 1)
        if unit and row.unit and unit.strip().lower() == row.unit.strip().lower():
            score += 0.1
        # Tie-break on the item code so a repeat run always picks the same row.
        if best is None or (score, row.item_code) > (best[0], best[1]):
            best = (score, row.item_code, row)
    if best is None or best[0] < 0.45:
        return None
    score, _code, row = best
    return {
        "item_code": row.item_code,
        "description": row.description,
        "unit": row.unit,
        "unit_price": float(row.base_unit_rate or 0.0),
        "currency": row.currency or "SAR",
        "score": round(score, 2),
        # Provenance: which list the rate came from, and who quoted it.
        "source": (row.notes or "").replace(NOTES_MARKER, "") or "manual",
        "supplier": row.supplier,
    }



def parse_csv_table(path: Path | str) -> list[dict]:
    """Parse a CSV/TSV price list with a REF/DESCRIPTION/Unit/price header."""
    import csv as _csv

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    delimiter = "\t" if str(path).lower().endswith(".tsv") else ","
    rows: list[dict] = []
    reader = _csv.reader(text.splitlines(), delimiter=delimiter)
    header: list[str] | None = None
    for cells in reader:
        cells = [c.strip() for c in cells]
        lowered = [c.lower() for c in cells]
        if header is None:
            if any(c.startswith("description") for c in lowered):
                header = lowered
            continue
        if not header or len(cells) < 2:
            continue
        def column(*names: str) -> int:
            for name in names:
                if name in header:
                    return header.index(name)
            return -1

        description = cells[column("description", "desc", "item description")] if column("description", "desc", "item description") >= 0 else ""
        if not description:
            continue
        ref_index = column("ref", "ref.", "item", "item code", "no")
        price_index = column("item price", "unit price", "u.p.", "rate", "price")
        unit_index = column("unit", "u", "uom")
        try:
            price = float(cells[price_index].replace(",", "")) if price_index >= 0 and price_index < len(cells) else 0.0
        except ValueError:
            price = 0.0
        rows.append(
            {
                "ref": (cells[ref_index] if 0 <= ref_index < len(cells) else "") or description[:40],
                "description": description,
                "unit": (cells[unit_index] if 0 <= unit_index < len(cells) else "") or "EA",
                "item_price": price,
                "total": 0.0,
            }
        )
    return rows

