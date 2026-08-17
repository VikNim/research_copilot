from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from research_copilot.models import LearningGoal


def find_by_title(session: Session, *, user_id: uuid.UUID, title: str) -> LearningGoal | None:
    """Case-insensitive exact match — same dedup pattern as
    collections_repo.find_by_name, so re-searching the same topic doesn't fork
    a new goal row every time."""
    stmt = select(LearningGoal).where(
        LearningGoal.user_id == user_id, func.lower(LearningGoal.title) == title.strip().lower()
    )
    return session.scalar(stmt)


def get_or_create_goal(session: Session, *, user_id: uuid.UUID, title: str) -> LearningGoal:
    """The actual entry point Screen 1 uses: a search *is* stating a learning
    goal, so this is called on every valid search submission — reuses an
    existing goal with the same title rather than creating a duplicate."""
    existing = find_by_title(session, user_id=user_id, title=title)
    if existing is not None:
        return existing
    return create_goal(session, user_id=user_id, title=title)


def create_goal(
    session: Session,
    *,
    user_id: uuid.UUID,
    title: str,
    description: str | None = None,
    target_level: str = "beginner",
    embedding: list[float] | None = None,
) -> LearningGoal:
    goal = LearningGoal(
        user_id=user_id,
        title=title,
        description=description,
        target_level=target_level,
        embedding=embedding,
    )
    session.add(goal)
    session.flush()
    return goal


def list_goals_for_user(session: Session, user_id: uuid.UUID) -> list[LearningGoal]:
    stmt = select(LearningGoal).where(LearningGoal.user_id == user_id).order_by(LearningGoal.created_at.desc())
    return list(session.scalars(stmt))


def get_goal(session: Session, goal_id: uuid.UUID) -> LearningGoal | None:
    return session.get(LearningGoal, goal_id)
