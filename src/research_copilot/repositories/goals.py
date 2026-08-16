from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from research_copilot.models import LearningGoal


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
