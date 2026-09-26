"""Ingest helper for corpus documents (stub for v2 Section 3)."""
from __future__ import annotations


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    """Naive chunker — split on paragraph boundaries, cap at max_chars."""
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for para in text.split("\n\n"):
        if cur + len(para) > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf = []
            cur = 0
        buf.append(para)
        cur += len(para)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks
