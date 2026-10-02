"""KAUST master reference: buildings, lot codes, LFOs, location codes.

Loaded once from app/reference_data/*.json (extracted from the standard
KAUST BLDGS.LIST, TRADES-LOTS and the 2014 Block & Stack) and indexed into
the AI corpus as a global reference, so a lot number or an LFO quoted in a
document resolves against the site's own list instead of the model's memory.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "reference_data"

#: "5-3610" -> building 5, level 3 (first digit), room 5-3610 (the full
#: code is the room number; the AREA is only explicit in the B7-L2-A3 form).
_ROOM_CODE = re.compile(r"\b(\d{1,2})\s*-\s*(\d)\d{2,4}\b")
#: "B7 L2 A3" / "BLDG 5 L3 A1"
_SHORT = re.compile(
    r"\b(?:b(?:ldg)?|building)\s*(\d{1,2})\s*[,; ]*"
    r"(?:l(?:vl)?|level)\s*(\d)\s*[,; ]*"
    r"(?:a|area)\s*(\d)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def buildings() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads((_DATA_DIR / "buildings.json").read_text("utf-8")))


@lru_cache(maxsize=1)
def lot_codes() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads((_DATA_DIR / "lot_codes.json").read_text("utf-8")))


@lru_cache(maxsize=1)
def lfos() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads((_DATA_DIR / "lfos.json").read_text("utf-8")))


def building_by_number(number: int) -> dict[str, Any] | None:
    return next((b for b in buildings() if b["number"] == number), None)


def lot_by_code(code: str) -> dict[str, Any] | None:
    wanted = (code or "").strip()
    for lot in lot_codes():
        if lot["code"] == wanted:
            return lot
    stripped = wanted.lstrip("0")
    for lot in lot_codes():
        if lot["code"].lstrip("0") == stripped and stripped:
            return lot
    return None


def lfo_by_number(number: int) -> dict[str, Any] | None:
    return next((l for l in lfos() if l["number"] == number), None)


def decode_location(text: str | None) -> dict[str, Any] | None:
    """Decode a location the way the site writes it.

    Two forms are understood, both in everyday use:

        5-3610      Building 5, Level 3, Area 1, Room 3610
        B7 L2 A3    Building 7, Level 2, Area 3

    Returns the parts plus the building's code and title from the master
    list, or None when nothing decodes. A building number that is not in the
    list still decodes - the site has annexes - but says so.
    """
    if not text:
        return None
    room = _ROOM_CODE.search(text)
    if room:
        building, level = room.groups()
        decoded: dict[str, Any] = {
            "building": int(building),
            "level": int(level),
            "area": None,
            "room": room.group(0),
            "form": "room-code",
        }
    else:
        short = _SHORT.search(text)
        if not short:
            return None
        building, level, area = short.groups()
        decoded = {
            "building": int(building),
            "level": int(level),
            "area": int(area),
            "room": None,
            "form": "short",
        }
    info = building_by_number(decoded["building"])
    decoded["building_code"] = info["code"] if info else None
    decoded["building_title"] = info["title"] if info else None
    decoded["known_building"] = info is not None
    return decoded


def describe_location(text: str | None) -> str | None:
    """One line for prompts and reports: 'B7 L2 A3 (NORTH RESEARCH LAB...)'."""
    decoded = decode_location(text)
    if not decoded:
        return None
    parts = [f"Building {decoded['building']}"]
    parts.append(f"Level {decoded['level']}")
    if decoded["area"] is not None:
        parts.append(f"Area {decoded['area']}")
    if decoded["room"]:
        parts.append(f"Room {decoded['room']}")
    line = ", ".join(parts)
    if decoded["building_title"]:
        line += f" ({decoded['building_code']} {decoded['building_title']})"
    elif decoded["form"] == "room-code":
        line += " (building not in the master list - verify)"
    return line


def ensure_reference_indexed(db) -> dict[str, int]:
    """Put the three lists into the corpus as global reference documents.

    Idempotent by filename, so calling it on every request is safe. The
    assistant and the document review then quote 'Lot 275 - Riyadh Stone
    Works' or 'LFO 2 - Nanobiophysics Lab (Chaieb)' from the site's own list
    instead of guessing.
    """
    from sqlalchemy import select

    from ..ai.corpus import chunk_text
    from ..models import CorpusChunk, CorpusDocument

    created = 0
    for name, rows in (
        ("reference/kaust-buildings", buildings()),
        ("reference/lot-codes", lot_codes()),
        ("reference/lfo-directory", lfos()),
    ):
        exists = db.scalar(
            select(CorpusDocument.id).where(CorpusDocument.filename == name)
        )
        if exists:
            continue
        if name.endswith("kaust-buildings"):
            text = "\n".join(
                f"Building {b['number']} - {b['code']} - {b['title']}" for b in rows
            )
        elif name.endswith("lot-codes"):
            text = "Standard lot list (code - description):\n" + "\n".join(
                f"Lot {l['code']} - {l['description']}" for l in rows
            )
        else:
            text = "LFO directory (number - laboratory / PI):\n" + "\n".join(
                f"LFO {l['number']} - {l['description']}" for l in rows
            )
        document = CorpusDocument(
            filename=name, source="reference", project_id=None,
            chunk_count=0, uploaded_by_id=1,
        )
        db.add(document)
        db.flush()
        for index, chunk in enumerate(chunk_text(text)):
            db.add(
                CorpusChunk(
                    document_id=document.id, project_id=None,
                    chunk_index=index, text=chunk,
                )
            )
        document.chunk_count = len(chunk_text(text))
        created += 1
    if created:
        db.commit()
    return {"indexed": created}
