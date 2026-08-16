"""Self-reported reading progress — not scroll/page tracking (Streamlit can't
observe that for externally-hosted content). See project memory for why."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from research_copilot.models import ReadingProgress

VALID_STATUSES = ("not_started", "in_progress", "done")


def set_status(
    session: Session,
    *,
    user_id: uuid.UUID,
    paper_id: str,
    status: str,
    collection_id: uuid.UUID | None = None,
) -> ReadingProgress:
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")

    stmt = select(ReadingProgress).where(
        ReadingProgress.user_id == user_id,
        ReadingProgress.paper_id == paper_id,
        ReadingProgress.collection_id == collection_id,
    )
    progress = session.scalar(stmt)
    now = datetime.now(timezone.utc)
    if progress is None:
        progress = ReadingProgress(user_id=user_id, paper_id=paper_id, collection_id=collection_id, status=status)
        session.add(progress)
    else:
        progress.status = status

    if status == "in_progress" and progress.started_at is None:
        progress.started_at = now
    if status == "done":
        progress.completed_at = now

    session.flush()
    return progress


def list_for_collection(session: Session, *, user_id: uuid.UUID, collection_id: uuid.UUID) -> dict[str, ReadingProgress]:
    stmt = select(ReadingProgress).where(
        ReadingProgress.user_id == user_id, ReadingProgress.collection_id == collection_id
    )
    return {p.paper_id: p for p in session.scalars(stmt)}


def recommend_next(session: Session, *, user_id: uuid.UUID, collection_id: uuid.UUID, ordered_paper_ids: list[str]) -> str | None:
    """First paper (in the collection's reading order) that isn't done yet."""
    progress_by_paper = list_for_collection(session, user_id=user_id, collection_id=collection_id)
    for paper_id in ordered_paper_ids:
        status = progress_by_paper.get(paper_id).status if paper_id in progress_by_paper else "not_started"
        if status != "done":
            return paper_id
    return None
