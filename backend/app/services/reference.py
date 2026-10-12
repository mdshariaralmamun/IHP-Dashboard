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


def _data_path(name: str) -> Path:
    """Locate a reference-data file wherever the app is running from.

    In the image the package is installed into site-packages, which does not
    carry the JSON masters, so the file is looked for beside the source, in the
    app directory and in the data directory before giving up.
    """
    candidates = [
        Path(__file__).resolve().parent / "reference_data",
        Path(__file__).resolve().parent.parent / "reference_data",
        Path(_DATA_DIR) / "reference_data",
        Path("/app/app/reference_data"),
        Path("/app/backend/app/reference_data"),
    ]
    for directory in candidates:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return candidates[0] / name


@lru_cache(maxsize=1)
def buildings() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(_data_path("buildings.json").read_text("utf-8")))


@lru_cache(maxsize=1)
def lot_codes() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(_data_path("lot_codes.json").read_text("utf-8")))


@lru_cache(maxsize=1)
def lfos() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(_data_path("lfos.json").read_text("utf-8")))


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


#: Room-number band -> area, as the team writes it on site. The band is the
#: digit after the level digit (5-0600 -> level 0, band 6). Bands 1..5 are
#: deliberately absent until the team confirms them.
AREA_BY_ROOM_BAND: dict[str, int] = {
    "6": 1,
    "7": 3,
    "8": 4,
    "9": 6,
}


#: The lab list (LAB LIST 02-2018): FLOC code -> lab, centre and PI, so a
#: location can answer "which lab is this?" in the site's own words.
_FLOC_LABS: dict[str, dict] | None = None


def floc_info(code: str | None) -> dict | None:
    """The lab the FLOC/room code belongs to, or None when it is not listed."""
    global _FLOC_LABS
    if not code:
        return None
    if _FLOC_LABS is None:
        import json
        from pathlib import Path

        try:
            path = _data_path("floc_labs.json")
            rows = json.loads(path.read_text(encoding="utf-8"))
            _FLOC_LABS = {str(row.get("floc", "")).strip(): row for row in rows}
        except Exception:  # noqa: BLE001 - a missing list must not break locations
            _FLOC_LABS = {}
    return _FLOC_LABS.get(str(code).strip())


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
        # The area of a room-code is the room number's band - the digit after
        # the level digit: 5-0600 is Level 0, band 6, Area 1 (as is 5-3610:
        # Level 3, band 6, Area 1). The team's mapping, given directly:
        #   6xx -> Area 1, 7xx -> Area 3, 8xx -> Area 4, 9xx -> Area 6.
        # Bands 1xx-5xx are not mapped yet - the team will confirm them - so
        # the area stays None rather than being guessed.
        # The code is building-level-room (5-0600 -> building 5, level 0, room
        # 600), so the band is the room number's first digit: index 2 of the
        # digits. 5-0600 -> 6 -> Area 1, 5-3610 -> 6 -> Area 1, 5-0700 -> 7 ->
        # Area 3.
        room_digits = "".join(ch for ch in str(decoded["room"]) if ch.isdigit())
        band = room_digits[2:3] if len(room_digits) > 2 else ""
        decoded["area"] = AREA_BY_ROOM_BAND.get(band)
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
    # Which lab it is, from the site's own lab list.
    lab = floc_info(decoded.get("room"))
    if lab and lab.get("lab"):
        detail = str(lab["lab"])
        # The centre is often already part of the lab's name - do not repeat it.
        if lab.get("centre") and str(lab["centre"]).lower() not in detail.lower():
            detail += f" ({lab['centre']})"
        if lab.get("pi"):
            detail += f" - PI: {lab['pi']}"
        line += " - " + detail
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
