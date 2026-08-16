"""Self-reported reading progress — not scroll/page tracking (Streamlit can't
observe that for externally-hosted content). See project memory for why.

Status-driven (not_started/in_progress/done), not a percentage — a percentage
slider was tried and reverted per user feedback ("I don't know how the
percentage bar is going to be helpful"). `progress_pct` still exists on the
table as a representative value (0/50/100) so it stays consistent with status
rather than going stale, but nothing in the UI exposes it directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from research_copilot.models import ReadingProgress

VALID_STATUSES = ("not_started", "in_progress", "done")
_REPRESENTATIVE_PCT = {"not_started": 0, "in_progress": 50, "done": 100}


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
    pct = _REPRESENTATIVE_PCT[status]
    if progress is None:
        progress = ReadingProgress(
            user_id=user_id, paper_id=paper_id, collection_id=collection_id,
            status=status, progress_pct=pct,
        )
        session.add(progress)
    else:
        progress.status = status
        progress.progress_pct = pct

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
