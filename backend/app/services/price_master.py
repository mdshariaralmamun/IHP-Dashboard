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

    deactivated = 0
    for code, pricing in by_code.items():
        if code not in seen and pricing.is_active:
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
