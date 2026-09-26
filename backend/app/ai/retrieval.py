"""Retrieval over the AI corpus (dashboard documents + engineering archive).

The platform stores every ingested document as text chunks in corpus_chunks
(source="archive" for the engineering archive, "attachment"/"upload" for
documents uploaded through the app). Until now nothing read them:
retrieval.search() was a stub returning [], and embeddings were never
computed, so the assistant had no access to documents at all.

Scoring is hybrid and degrades gracefully:
  * keyword overlap  - needs no model, always available
  * embedding cosine - used when the chunk carries a vector (Ollama was
    online at ingest time) and the provider can embed the question now

Vectors are stored as JSON and compared in Python rather than in pgvector, so
SQLite (dev) and Postgres (prod) behave identically. Candidates are narrowed
with a SQL keyword filter first, which keeps a query over tens of thousands of
chunks in the tens of milliseconds. When the corpus grows past ~100k chunks the
next step is a pgvector column + HNSW index; see docs/AI_LOCAL_MODEL_PLAN.md.
"""

from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CorpusChunk, CorpusDocument
from . import provider

#: Words that carry no retrieval signal in this domain.
_STOP = {
    "the", "and", "for", "with", "from", "into", "about", "this", "that",
    "these", "those", "there", "their", "have", "has", "had", "was", "were",
    "are", "is", "be", "been", "being", "will", "would", "should", "could",
    "can", "may", "might", "you", "your", "our", "we", "i", "me", "my", "it",
    "its", "they", "them", "he", "she", "his", "her", "what", "which", "who",
    "whom", "when", "where", "why", "how", "does", "did", "do", "done", "any",
    "all", "some", "more", "most", "much", "many", "not", "no", "yes", "but",
    "also", "please", "tell", "show", "give", "need", "want", "used", "use",
    "using", "get", "got", "one", "two", "new", "old", "same", "other",
}

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-_/.]{2,}")
_MAX_PREFILTER_TOKENS = 4


def tokens(value: str) -> set[str]:
    """Lowercase search tokens (>=3 chars, stop words removed)."""
    return {
        t for t in _TOKEN.findall((value or "").lower())
        if t not in _STOP and not t.isdigit()
    }


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def _keyword_score(query_tokens: set[str], chunk_tokens: set[str]) -> float:
    if not query_tokens or not chunk_tokens:
        return 0.0
    overlap = len(query_tokens & chunk_tokens)
    if not overlap:
        return 0.0
    # Precision matters more than recall for document answers, and a short
    # hit (a 40-token BOQ row) should not outrank a full page of explanation.
    precision = overlap / len(chunk_tokens) ** 0.5
    coverage = overlap / len(query_tokens)
    return 0.65 * coverage + 0.35 * min(precision, 3.0) / 3.0


def _row(chunk: CorpusChunk, filename: str, score: float, keyword: float,
         vector: float) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "filename": filename,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "project_id": chunk.project_id,
        "score": round(score, 4),
        "keyword_score": round(keyword, 4),
        "vector_score": round(vector, 4),
    }


def search(
    query: str,
    db: Session,
    k: int = 5,
    project_id: int | None = None,
    include_global: bool = True,
    candidate_limit: int = 800,
    max_chars: int = 1400,
) -> list[dict[str, Any]]:
    """Return up to k {filename, text, score, ...} chunks relevant to query."""
    query = (query or "").strip()
    if not query:
        return []
    query_tokens = tokens(query)

    stmt = (
        select(CorpusChunk, CorpusDocument.filename)
        .join(CorpusDocument, CorpusDocument.id == CorpusChunk.document_id)
    )
    if project_id is not None:
        if include_global:
            stmt = stmt.where(
                (CorpusChunk.project_id == project_id)
                | (CorpusChunk.project_id.is_(None))
            )
        else:
            stmt = stmt.where(CorpusChunk.project_id == project_id)

    # ---- candidate narrowing: cheapest rare-ish tokens as SQL filters -------
    candidates: list[tuple[CorpusChunk, str]] = []
    if query_tokens:
        # Prefer the longest tokens: they are the most selective in practice.
        ordered = sorted(query_tokens, key=len, reverse=True)[:_MAX_PREFILTER_TOKENS]
        condition = None
        for token in ordered:
            like = CorpusChunk.text.ilike(f"%{token}%")
            condition = like if condition is None else condition | like
        if condition is not None:
            rows = db.execute(
                stmt.where(condition).limit(candidate_limit)
            ).all()
            candidates = [(r[0], r[1]) for r in rows]

    # Nothing matched by keyword: fall back to a bounded scan of embedded
    # chunks so purely semantic questions still find something.
    embedded_scan = False
    if not candidates:
        rows = db.execute(
            stmt.where(CorpusChunk.embedding.isnot(None))
            .order_by(CorpusChunk.id.desc())
            .limit(2000)
        ).all()
        candidates = [(r[0], r[1]) for r in rows]
        embedded_scan = True

    if not candidates:
        return []

    # ---- vector half (optional) -------------------------------------------
    query_vector: list[float] | None = None
    if any(chunk.embedding for chunk, _ in candidates):
        query_vector = provider.embed(query)

    scored: list[dict[str, Any]] = []
    for chunk, filename in candidates:
        keyword = _keyword_score(query_tokens, tokens(chunk.text))
        vector = 0.0
        if query_vector and chunk.embedding:
            vector = max(_cosine(query_vector, chunk.embedding), 0.0)
        if query_vector:
            score = 0.45 * keyword + 0.55 * vector
        else:
            score = keyword
        if score <= 0:
            continue
        scored.append(_row(chunk, filename, score, keyword, vector))

    scored.sort(key=lambda item: item["score"], reverse=True)

    # Keep the prompt small and de-duplicate near-identical chunks.
    out: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for hit in scored:
        fingerprint = hit["text"][:160]
        if fingerprint in seen_text:
            continue
        seen_text.add(fingerprint)
        out.append({**hit, "text": hit["text"][:max_chars]})
        if len(out) >= k:
            break

    for hit in out:
        hit["semantic_only"] = embedded_scan
    return out


def stats(db: Session) -> dict[str, Any]:
    """Corpus size, so the UI can show whether retrieval has anything to use."""
    documents = db.scalar(select(func.count(CorpusDocument.id))) or 0
    chunks = db.scalar(select(func.count(CorpusChunk.id))) or 0
    embedded = db.scalar(
        select(func.count(CorpusChunk.id)).where(CorpusChunk.embedding.isnot(None))
    ) or 0
    by_source = db.execute(
        select(CorpusDocument.source, func.count(CorpusDocument.id))
        .group_by(CorpusDocument.source)
    ).all()
    return {
        "documents": documents,
        "chunks": chunks,
        "embedded_chunks": embedded,
        "by_source": {str(row[0]): int(row[1]) for row in by_source},
    }
