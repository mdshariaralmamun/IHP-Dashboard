"""Whose court is the project in?

The EAR/Design/Procore boards exist to answer one question per project:
what has to happen next, and is it US who has to do it? Two documents decide
that - the MOM and the Project Summary - each with the same lifecycle:

    (nothing) -> draft -> sent -> acknowledged        (disputed anywhere)

A document that does not exist or is a draft is OUR move. A sent document is
the PI's move, and the only thing we can do about it is follow up. Everything
acknowledged means the phase's paperwork is done and the project moves on.

A project in OUR court blinks on the board: that is the list of things the
team must actually do today.
"""

from __future__ import annotations

from typing import Any

#: The lifecycle statuses a document can carry (MOM uses these natively; the
#: Project Summary column stores the same vocabulary).
DOC_STATUSES = ("draft", "sent", "acknowledged", "disputed")


def _document_court(status: str | None, name: str) -> dict[str, Any]:
    """Court + action for one document (MOM or Project Summary)."""
    status = (status or "").strip().lower() or None
    if status == "acknowledged":
        return {"status": status, "court": "done", "action": None}
    if status == "sent":
        return {
            "status": status,
            "court": "PI",
            "action": f"Follow up with the PI: {name} acknowledgment",
        }
    if status == "disputed":
        return {
            "status": status,
            "court": "IHP",
            "action": f"Resolve the dispute on the {name}",
        }
    # Not started, or still a draft: writing and sending it is our move.
    label = "Generate" if status is None else "Send"
    return {
        "status": status or "none",
        "court": "IHP",
        "action": f"{label} the {name}",
    }


def project_court(project: Any, mom_status: str | None) -> dict[str, Any]:
    """Everything the board shows, computed - never stored - so it cannot go
    stale against the MOM record."""
    mom = _document_court(mom_status, "MOM")
    summary = _document_court(project.summary_status, "Project Summary")

    our_moves = [
        doc["action"] for doc in (mom, summary)
        if doc["court"] == "IHP" and doc["action"]
    ]
    their_moves = [
        doc["action"] for doc in (mom, summary)
        if doc["court"] == "PI" and doc["action"]
    ]
    return {
        "mom": mom,
        "summary": summary,
        "my_court": bool(our_moves),
        "next_action": our_moves[0] if our_moves else None,
        "waiting_on": "PI" if their_moves and not our_moves else None,
        "our_moves": our_moves,
        "their_moves": their_moves,
    }
