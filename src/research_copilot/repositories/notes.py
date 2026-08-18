"""Two note scopes, one table (see models.Note): paper-scoped (about that paper's
content) and collection-scoped (about the topic/goal as a whole)."""

from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from research_copilot.models import Note

# An AI-generated summary is stored as a regular note (no separate table/column
# for it) but needs to read as its own distinct thing, not an anonymous note
# that happens to say the same thing as the paper — this marker is how both the
# writer (Workspace's "Add summary to collection") and readers (the badge in
# collection paper lists) agree on what counts as "the summary", without a
# schema change.
AI_SUMMARY_LABEL = "✨ AI Summary"


def format_summary_note(summary: str) -> str:
    return f"**{AI_SUMMARY_LABEL}**\n\n{summary}"


def has_ai_summary(session: Session, *, user_id: uuid.UUID, paper_id: str) -> bool:
    stmt = select(
        exists().where(
            Note.user_id == user_id, Note.paper_id == paper_id, Note.content.startswith(f"**{AI_SUMMARY_LABEL}**")
        )
    )
    return bool(session.scalar(stmt))


def add_note(
    session: Session,
    *,
    user_id: uuid.UUID,
    content: str,
    paper_id: str | None = None,
    collection_id: uuid.UUID | None = None,
    embedding: list[float] | None = None,
) -> Note:
    if paper_id is None and collection_id is None:
        raise ValueError("a note must be scoped to a paper_id and/or a collection_id")
    note = Note(user_id=user_id, paper_id=paper_id, collection_id=collection_id, content=content, embedding=embedding)
    session.add(note)
    session.flush()
    return note


def list_for_paper(session: Session, *, user_id: uuid.UUID, paper_id: str) -> list[Note]:
    stmt = (
        select(Note)
        .where(Note.user_id == user_id, Note.paper_id == paper_id)
        .order_by(Note.created_at.desc())
    )
    return list(session.scalars(stmt))


def list_for_collection(session: Session, *, user_id: uuid.UUID, collection_id: uuid.UUID) -> list[Note]:
    """Collection-level notes only (paper_id is null) — not the notes of papers inside it."""
    stmt = (
        select(Note)
        .where(Note.user_id == user_id, Note.collection_id == collection_id, Note.paper_id.is_(None))
        .order_by(Note.created_at.desc())
    )
    return list(session.scalars(stmt))
