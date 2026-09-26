"""Local fine-tuning data: capture feedback, export a chat SFT dataset.

Why this exists
---------------
A local model can be *adapted* on this server, but only for the things
fine-tuning is actually good at: style, format and domain vocabulary. Facts
must keep coming from the database and the document corpus, because a
fine-tuned 1B model still hallucinates numbers - and stale numbers in a
trained model are worse than no answer at all.

So this module builds the raw material for that adaptation:

  * every 👍/👎 the user leaves is appended to ai_feedback.jsonl, together
    with the live answer, the question, the mode and the sources; and
  * export_dataset() writes a chat-format JSONL (instruction -> answer) built
    from rated-good answers plus synthetic question/answer pairs taken from
    the live fact pack, where the facts are exact by construction.

That file feeds the LoRA recipe in docs/AI_LOCAL_MODEL_PLAN.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..ai import facts as facts_mod
from ..core.config import get_settings


def _data_dir() -> Path:
    path = Path(get_settings().DATA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def feedback_file() -> Path:
    return _data_dir() / "ai_feedback.jsonl"


def dataset_file() -> Path:
    return _data_dir() / "training" / "ihp_sft.jsonl"


def record_feedback(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Append one rated answer. Never raises for a well-formed payload."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_id": user_id,
        "rating": str(payload.get("rating") or "")[:8],
        "mode": str(payload.get("mode") or "")[:16],
        "model": str(payload.get("model") or "")[:64],
        "project_id": payload.get("project_id"),
        "question": str(payload.get("question") or "")[:2000],
        "answer": str(payload.get("answer") or "")[:8000],
        "comment": str(payload.get("comment") or "")[:1000],
        "sources": (payload.get("sources") or [])[:8],
    }
    with feedback_file().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"recorded": True, "file": str(feedback_file())}


def feedback_stats() -> dict[str, Any]:
    path = feedback_file()
    if not path.exists():
        return {"total": 0, "up": 0, "down": 0, "by_mode": {}}
    total = up = down = 0
    by_mode: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        if entry.get("rating") == "up":
            up += 1
        elif entry.get("rating") == "down":
            down += 1
        mode = str(entry.get("mode") or "?")
        by_mode[mode] = by_mode.get(mode, 0) + 1
    return {"total": total, "up": up, "down": down, "by_mode": by_mode}


SYSTEM_TEXT = (
    "You are the KAUST IHP (Infrastructure & Housing Projects) assistant. "
    "Answer from the live project data with exact numbers, name the PR number, "
    "and say so when the data does not contain the answer."
)

#: Straight from the deterministic layer, so both sides are exact.
_SYNTHETIC_QUESTIONS = [
    "How many projects are there in total?",
    "How many projects are in each division?",
    "Which projects are overdue?",
    "Which projects are due this week?",
    "Which projects are on hold?",
    "How many projects are in the Construction division?",
    "How many projects are at the ICR / approval stage?",
    "How many projects are at the Punch List stage?",
    "How many projects have no Planner finish date?",
]


def _write_jsonl(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def export_dataset(db: Session, out_path: Path | None = None) -> dict[str, Any]:
    """Write a chat-format JSONL dataset from rated answers + live facts."""
    out_path = out_path or dataset_file()
    rows: list[dict[str, Any]] = []

    # 1. Answers the Planner marked as good.
    path = feedback_file()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("rating") != "up":
                continue
            question = (entry.get("question") or "").strip()
            answer = (entry.get("answer") or "").strip()
            if question and answer:
                rows.append({
                    "messages": [
                        {"role": "system", "content": SYSTEM_TEXT},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ]
                })

    # 2. Exact question/answer pairs generated from the live fact pack.
    try:
        pack = facts_mod.collect(db)
        for question in _SYNTHETIC_QUESTIONS:
            answer = facts_mod.answer(question, pack)
            if not answer:
                continue
            rows.append({
                "messages": [
                    {"role": "system", "content": SYSTEM_TEXT},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ]
            })
    except Exception as exc:  # noqa: BLE001 — dataset export must not 500
        return {"written": 0, "path": str(out_path), "error": str(exc)[:200]}

    _write_jsonl(rows, out_path)
    return {
        "written": len(rows),
        "path": str(out_path),
        "bytes": out_path.stat().st_size if out_path.exists() else 0,
    }
