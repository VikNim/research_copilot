from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from research_copilot.models import Collection, CollectionPaper, Paper


def find_by_name(session: Session, *, user_id: uuid.UUID, name: str) -> Collection | None:
    """Case-insensitive exact match — used to catch a user re-searching a topic
    they already have a saved collection for, so Save doesn't silently fork it."""
    stmt = select(Collection).where(
        Collection.user_id == user_id, func.lower(Collection.name) == name.strip().lower()
    )
    return session.scalar(stmt)


def create_collection(
    session: Session,
    *,
    user_id: uuid.UUID,
    name: str,
    learning_goal_id: uuid.UUID | None = None,
    description: str | None = None,
) -> Collection:
    collection = Collection(user_id=user_id, name=name, learning_goal_id=learning_goal_id, description=description)
    session.add(collection)
    session.flush()
    return collection


def list_collections_for_user(session: Session, user_id: uuid.UUID) -> list[Collection]:
    stmt = select(Collection).where(Collection.user_id == user_id).order_by(Collection.created_at.desc())
    return list(session.scalars(stmt))


def get_collection(session: Session, collection_id: uuid.UUID) -> Collection | None:
    """Unscoped — the caller is responsible for checking .user_id before trusting
    or displaying the result (see get_owned_collection for the checked version,
    which every caller working from a not-fully-trusted collection_id should use)."""
    return session.get(Collection, collection_id)


def get_owned_collection(session: Session, collection_id: uuid.UUID, user_id: uuid.UUID) -> Collection | None:
    """Returns the collection only if it belongs to user_id — None both when it
    doesn't exist AND when it belongs to someone else, deliberately indistinguishable
    so a caller can't use this to probe whether an id exists at all. Use this (not
    get_collection) anywhere a collection_id arrives from a source that isn't
    already provably scoped to the current user — session_state that could in
    principle be tampered with, or arguments an LLM tool call supplies."""
    stmt = select(Collection).where(Collection.id == collection_id, Collection.user_id == user_id)
    return session.scalar(stmt)


def add_paper(session: Session, *, collection_id: uuid.UUID, paper_id: str, position: int | None = None) -> CollectionPaper:
    """Idempotent — adding a paper that's already in the collection is a no-op,
    on purpose: a double-click or the same action fired from two tabs shouldn't
    error. `ON CONFLICT DO NOTHING` makes that atomic instead of a racy
    get-then-insert (a rare position tie between two truly simultaneous adds of
    *different* papers is possible but harmless — worst case a shared reading-order
    number, not a crash or lost data)."""
    if position is None:
        current_max = session.scalar(
            select(CollectionPaper.position)
            .where(CollectionPaper.collection_id == collection_id)
            .order_by(CollectionPaper.position.desc())
            .limit(1)
        )
        position = (current_max or 0) + 1
    stmt = pg_insert(CollectionPaper).values(collection_id=collection_id, paper_id=paper_id, position=position)
    stmt = stmt.on_conflict_do_nothing(index_elements=[CollectionPaper.collection_id, CollectionPaper.paper_id])
    session.execute(stmt)
    session.flush()
    # populate_existing: DO NOTHING still needs this on the *first* insert path too,
    # in case this collection/paper pair's row was loaded earlier in this session
    # via a different query and would otherwise return a stale identity-mapped copy.
    return session.get(
        CollectionPaper, {"collection_id": collection_id, "paper_id": paper_id}, populate_existing=True
    )


def remove_paper(session: Session, *, collection_id: uuid.UUID, paper_id: str) -> None:
    link = session.get(CollectionPaper, {"collection_id": collection_id, "paper_id": paper_id})
    if link:
        session.delete(link)
        session.flush()


def set_positions(session: Session, collection_id: uuid.UUID, ordered_paper_ids: list[str]) -> None:
    """Applies a sequencing result (see sequencing.py) as the collection's reading order."""
    for position, paper_id in enumerate(ordered_paper_ids):
        link = session.get(CollectionPaper, {"collection_id": collection_id, "paper_id": paper_id})
        if link:
            link.position = position
    session.flush()


def list_papers_in_collection(session: Session, collection_id: uuid.UUID) -> list[Paper]:
    stmt = (
        select(Paper)
        .join(CollectionPaper, CollectionPaper.paper_id == Paper.id)
        .where(CollectionPaper.collection_id == collection_id)
        .order_by(CollectionPaper.position)
    )
    return list(session.scalars(stmt))
