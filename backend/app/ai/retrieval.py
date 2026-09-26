"""Retrieval-augmented search (stub for v2 Section 3).

Per v2 spec Section 3, retrieval is scoped per logical folder in
ENGINEERING_DATA (project archive vs standards vs codes) and surfaces
citations for compliance/feasibility checks (Section 4).
"""

from __future__ import annotations

from typing import Any


def search(query: str, db: Any, k: int = 5) -> list[dict[str, Any]]:
    """Return up to k {filename, text} hits. Stub: returns [].

    Section 3 replaces this with the watched-folder ingestion pipeline
    + scoped retrieval (per-folder, per-project).
    """
    return []
