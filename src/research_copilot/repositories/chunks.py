"""Full-text storage for one paper (see fulltext.py for how chunks get here).

No unique constraint on (paper_id, chunk_index) — re-ingestion is rare enough
(on-demand, once per paper) that delete-then-insert is simpler than an upsert
and needs no schema migration."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from research_copilot.models import PaperChunk


def has_chunks(session: Session, paper_id: str) -> bool:
    stmt = select(PaperChunk.id).where(PaperChunk.paper_id == paper_id).limit(1)
    return session.scalar(stmt) is not None


def get_full_text(session: Session, paper_id: str) -> str | None:
    stmt = (
        select(PaperChunk.chunk_text)
        .where(PaperChunk.paper_id == paper_id)
        .order_by(PaperChunk.chunk_index)
    )
    pieces = list(session.scalars(stmt))
    return "\n\n".join(pieces) if pieces else None


def store_chunks(session: Session, paper_id: str, chunk_texts: list[str]) -> None:
    session.execute(delete(PaperChunk).where(PaperChunk.paper_id == paper_id))
    for i, text in enumerate(chunk_texts):
        session.add(PaperChunk(paper_id=paper_id, chunk_index=i, chunk_text=text))
    session.flush()
