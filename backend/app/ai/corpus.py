"""Ingest helper for corpus documents (stub for v2 Section 3)."""
from __future__ import annotations


def sanitize_text(text: str) -> str:
    """Drop characters Postgres text columns reject (NUL) and normalise newlines.

    PDF text extraction regularly emits 0x00 bytes, and "PostgreSQL text fields
    cannot contain NUL" aborted a whole archive ingest after 344 documents.
    """
    if not text:
        return ""
    return (
        text.replace("\x00", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


#: Split a long block at a sentence, clause or tab boundary.
_BOUNDARY = (". ", "; ", ": ", "\t")


def _split_long(block: str, max_chars: int) -> list[str]:
    """Hard-split a block that is longer than one chunk."""
    out: list[str] = []
    for line in block.split("\n"):
        rest = line
        while len(rest) > max_chars:
            window = rest[:max_chars]
            cut = max(window.rfind(mark) for mark in _BOUNDARY) + 1
            if cut < max_chars // 2:
                cut = max_chars
            piece = rest[:cut].strip()
            if piece:
                out.append(piece)
            rest = rest[cut:]
        if rest.strip():
            out.append(rest)
    return out


def chunk_text(text: str, max_chars: int = 2000) -> list[str]:
    """Split text into retrieval chunks of at most max_chars.

    Extracted PDF/Excel text often has no blank lines at all, so a purely
    paragraph-based split produced single 50 KB chunks (one whole report):
    the embedding of such a chunk is meaningless and the prompt cannot hold it.
    Every chunk is therefore hard-bounded, preferring paragraph, then line,
    then sentence boundaries.
    """
    text = sanitize_text(text)
    units: list[str] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        if len(block) <= max_chars:
            units.append(block.strip())
        else:
            units.extend(piece for piece in _split_long(block, max_chars) if piece)

    chunks: list[str] = []
    buffer = ""
    for unit in units:
        candidate = (buffer + "\n" + unit) if buffer else unit
        if len(candidate) > max_chars and buffer:
            chunks.append(buffer)
            buffer = unit
        else:
            buffer = candidate
    if buffer:
        chunks.append(buffer)
    return chunks
