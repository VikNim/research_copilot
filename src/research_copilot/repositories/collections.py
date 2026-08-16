from __future__ import annotations

import uuid

from sqlalchemy import func, select
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
    return session.get(Collection, collection_id)


def add_paper(session: Session, *, collection_id: uuid.UUID, paper_id: str, position: int | None = None) -> CollectionPaper:
    existing = session.get(CollectionPaper, {"collection_id": collection_id, "paper_id": paper_id})
    if existing:
        return existing
    if position is None:
        current_max = session.scalar(
            select(CollectionPaper.position)
            .where(CollectionPaper.collection_id == collection_id)
            .order_by(CollectionPaper.position.desc())
            .limit(1)
        )
        position = (current_max or 0) + 1
    link = CollectionPaper(collection_id=collection_id, paper_id=paper_id, position=position)
    session.add(link)
    session.flush()
    return link


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
