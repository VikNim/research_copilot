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

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from research_copilot.models import ReadingProgress

VALID_STATUSES = ("not_started", "in_progress", "done")
_REPRESENTATIVE_PCT = {"not_started": 0, "in_progress": 50, "done": 100}
STATUS_LABELS = {"not_started": "Not yet opened", "in_progress": "In progress", "done": "Finished reading"}


def set_status(
    session: Session,
    *,
    user_id: uuid.UUID,
    paper_id: str,
    status: str,
    collection_id: uuid.UUID | None = None,
) -> ReadingProgress:
    """Atomic upsert (not check-then-insert) for the same reason as papers_repo/
    users_repo/collections_repo — two tabs on the same account updating the same
    paper's progress at once shouldn't race. `started_at` is preserved once set
    (via CASE against the pre-existing row) rather than reset on every update.

    Known limitation: this relies on the `uq_progress_scope` unique constraint to
    detect "already exists", and Postgres does not treat two NULLs as conflicting
    in a unique constraint — so with `collection_id=None`, ON CONFLICT never
    fires and each call inserts a new row instead of updating. Not a problem in
    practice: every call site in the app passes a real collection_id (progress is
    always tracked per-collection); this only matters for the unused
    collection-agnostic case the signature still technically allows."""
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")

    now = datetime.now(timezone.utc)
    pct = _REPRESENTATIVE_PCT[status]
    stmt = pg_insert(ReadingProgress).values(
        user_id=user_id, paper_id=paper_id, collection_id=collection_id,
        status=status, progress_pct=pct,
        started_at=now if status == "in_progress" else None,
        completed_at=now if status == "done" else None,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_progress_scope",
        set_={
            "status": stmt.excluded.status,
            "progress_pct": stmt.excluded.progress_pct,
            "started_at": case(
                (ReadingProgress.started_at.is_not(None), ReadingProgress.started_at),
                else_=stmt.excluded.started_at,
            ),
            "completed_at": case(
                (stmt.excluded.status == "done", stmt.excluded.completed_at),
                else_=ReadingProgress.completed_at,
            ),
        },
    )
    session.execute(stmt)
    session.flush()
    # populate_existing: see users_repo.upsert_user — same identity-map staleness
    # risk, and this function is called repeatedly on the same row (status changes).
    return session.scalar(
        select(ReadingProgress)
        .where(
            ReadingProgress.user_id == user_id,
            ReadingProgress.paper_id == paper_id,
            ReadingProgress.collection_id == collection_id,
        )
        .execution_options(populate_existing=True)
    )


def list_for_collection(session: Session, *, user_id: uuid.UUID, collection_id: uuid.UUID) -> dict[str, ReadingProgress]:
    stmt = select(ReadingProgress).where(
        ReadingProgress.user_id == user_id, ReadingProgress.collection_id == collection_id
    )
    return {p.paper_id: p for p in session.scalars(stmt)}


def mark_started(session: Session, *, user_id: uuid.UUID, paper_id: str, collection_id: uuid.UUID) -> None:
    """Bumps not_started -> in_progress. Called when a paper is actually opened to
    read, not just listed — never downgrades an already in_progress/done paper."""
    current = list_for_collection(session, user_id=user_id, collection_id=collection_id).get(paper_id)
    if current is None or current.status == "not_started":
        set_status(session, user_id=user_id, paper_id=paper_id, status="in_progress", collection_id=collection_id)


def recommend_next(session: Session, *, user_id: uuid.UUID, collection_id: uuid.UUID, ordered_paper_ids: list[str]) -> str | None:
    """First paper (in the collection's reading order) that isn't done yet."""
    progress_by_paper = list_for_collection(session, user_id=user_id, collection_id=collection_id)
    for paper_id in ordered_paper_ids:
        status = progress_by_paper.get(paper_id).status if paper_id in progress_by_paper else "not_started"
        if status != "done":
            return paper_id
    return None
