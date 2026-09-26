"""Project archive index + similarity search.

The engineering archive (ENGINEERING_DATA) keeps one folder per past project,
named after the PR:

    PR 10008 Relocation and re-installation of Maxis from Surplus EAR 9778
    PR 10223 Addition of ventilated cupboard ...... project Cancellation

plus reference material (specifications, standards, BOQ samples).

This module walks the archive once, parses those names into structured
records, and scores them against a live project so the platform can suggest
"similar work we have done before" when drafting the MOM, Project Summary,
SOW, BOQ or MTO.

Scoring is deterministic (token overlap + trade + division signals) so it
works offline and gives explainable matches; the LLM layer is only used to
write the final wording.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: "PR 10008 Title here EAR 9778" / "PR 10305 - Title - John Rahmer EAR 10121"
_PR_HEAD = re.compile(r"^\s*PR[\s.\-]*(\d{4,6})\b(.*)$", re.I)
_EAR_TAIL = re.compile(r"\bEAR[\s#.:\-]*(\d{4,6})\b", re.I)
_CANCELLED = re.compile(r"cancell?ation|cancell?ed", re.I)
#: Folders that are reference material, not projects.
_NON_PROJECT = re.compile(
    r"^(\d+(_|\.)|BS Materials|General Template|ICR-WCC|Manpower Plan|"
    r"IHP Weekly|Electrical &|Scope Sample|MEP |Bld-|autocad|Specifications)",
    re.I,
)

_STOP = {
    "pr", "ear", "the", "of", "and", "for", "to", "in", "on", "at", "with", "a",
    "an", "installation", "install", "new", "internal", "due", "by", "from",
}

#: Documents worth surfacing as "what we produced last time".
DOC_KINDS: tuple[tuple[str, str], ...] = (
    ("sow", r"scope of work|\bsow\b"),
    ("boq", r"\bboq\b|bill of quantit"),
    ("mto", r"\bmto\b|material take"),
    ("ear", r"\bear\b|engineering assessment"),
    ("mom", r"\bmom\b|minutes of meeting"),
    ("summary", r"project summary|summary"),
    ("drawing", r"drawing|\bdwg\b|autocad|\.dwg$"),
    ("quotation", r"quot|rfq|proposal"),
    ("wcc", r"\bwcc\b|work completion"),
    ("wch", r"\bwch\b|handover"),
    ("permit", r"permit|\bptw\b|wicf"),
    ("budget", r"budget|cost estimate|pricing"),
)


@dataclass
class ArchiveProject:
    """One archived project folder."""

    name: str
    path: str
    pr_number: str | None = None
    ear_number: str | None = None
    title: str = ""
    cancelled: bool = False
    file_count: int = 0
    doc_kinds: list[str] = field(default_factory=list)
    sample_files: list[str] = field(default_factory=list)
    modified: str | None = None
    tokens: list[str] = field(default_factory=list)

    def to_dict(self, include_tokens: bool = False) -> dict:
        d = asdict(self)
        if not include_tokens:
            d.pop("tokens", None)
        return d


def tokens_for(text: str) -> list[str]:
    """Lower-case word tokens with stop words and numbering stripped."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w for w in words if w not in _STOP and len(w) > 2 and not w.isdigit()]


def parse_folder(name: str) -> tuple[str | None, str | None, str, bool]:
    """(pr_number, ear_number, title, cancelled) from a folder name."""
    cancelled = bool(_CANCELLED.search(name))
    m = _PR_HEAD.match(name)
    if not m:
        return None, None, name.strip(), cancelled
    pr = f"PR-{m.group(1)}"
    rest = m.group(2)
    ear = _EAR_TAIL.search(rest)
    ear_number = f"EAR-{ear.group(1)}" if ear else None
    title = _EAR_TAIL.sub("", rest)
    title = re.sub(r"[.\-_]{2,}", " ", title)
    title = re.sub(r"\bproject\s+cancell?ation\b", "", title, flags=re.I)
    title = re.sub(r"\s{2,}", " ", title).strip(" -.\u2013\u2014:")
    return pr, ear_number, title or name.strip(), cancelled


def _doc_kinds(names: list[str]) -> list[str]:
    joined = " | ".join(n.lower() for n in names)
    return [kind for kind, pattern in DOC_KINDS if re.search(pattern, joined, re.I)]


def scan(root: Path | str, max_files_per_project: int = 400) -> list[ArchiveProject]:
    """Walk the archive root and return one record per project folder."""
    root = Path(root)
    if not root.is_dir():
        return []
    out: list[ArchiveProject] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or _NON_PROJECT.match(entry.name):
            continue
        pr, ear, title, cancelled = parse_folder(entry.name)
        if pr is None:
            continue
        files: list[str] = []
        try:
            for f in entry.rglob("*"):
                if f.is_file():
                    files.append(f.name)
                    if len(files) >= max_files_per_project:
                        break
        except OSError:
            pass
        try:
            modified = time.strftime(
                "%Y-%m-%d", time.localtime(entry.stat().st_mtime)
            )
        except OSError:
            modified = None
        out.append(ArchiveProject(
            name=entry.name,
            path=str(entry),
            pr_number=pr,
            ear_number=ear,
            title=title,
            cancelled=cancelled,
            file_count=len(files),
            doc_kinds=_doc_kinds(files),
            sample_files=files[:12],
            modified=modified,
            tokens=tokens_for(f"{title} {entry.name}"),
        ))
    return out


def build_index(root: Path | str, out_file: Path | str) -> dict:
    """Scan the archive and write the index JSON. Returns a small summary."""
    projects = scan(root)
    payload = {
        "root": str(root),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(projects),
        "projects": [p.to_dict(include_tokens=True) for p in projects],
    }
    out = Path(out_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")
    return {
        "root": str(root),
        "count": len(projects),
        "cancelled": sum(1 for p in projects if p.cancelled),
        "with_ear": sum(1 for p in projects if p.ear_number),
        "built_at": payload["built_at"],
        "index_file": str(out),
    }


def load_index(index_file: Path | str) -> dict | None:
    path = Path(index_file)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def score(query_tokens: set[str], query_trades: set[str], item: dict) -> tuple[float, list[str]]:
    """Similarity of one archive project to the query. Higher is better."""
    toks = set(item.get("tokens") or [])
    if not toks or not query_tokens:
        return 0.0, []
    shared = query_tokens & toks
    # Overlap coefficient: forgiving when the archive title is much longer.
    overlap = len(shared) / max(len(query_tokens), 1)
    jaccard = len(shared) / max(len(query_tokens | toks), 1)
    base = 0.7 * overlap + 0.3 * jaccard

    kinds = set(item.get("doc_kinds") or [])
    if {"sow", "boq", "mto"} & kinds:
        base += 0.06  # we have the documents we are about to write
    if item.get("cancelled"):
        base -= 0.10   # a cancelled precedent is weaker evidence
    if query_trades & kinds:
        base += 0.04
    return round(min(base, 1.0), 4), sorted(shared)


def similar(index: dict | None, title: str, trades: list[str] | None = None,
            division: str | None = None, exclude_pr: str | None = None,
            limit: int = 8) -> list[dict]:
    """Rank archive projects by similarity to the given project."""
    if not index:
        return []
    q_tokens = set(tokens_for(title))
    q_trades = {t.lower() for t in (trades or [])}
    q_tokens |= q_trades
    if division:
        q_tokens |= set(tokens_for(division))
    ranked: list[dict] = []
    for item in index.get("projects", []):
        if exclude_pr and item.get("pr_number") == exclude_pr:
            continue
        s, terms = score(q_tokens, q_trades, item)
        if s <= 0:
            continue
        d = {k: v for k, v in item.items() if k != "tokens"}
        d["score"] = s
        d["matched_terms"] = terms[:10]
        ranked.append(d)
    ranked.sort(key=lambda d: -d["score"])
    return ranked[:limit]
