from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from research_copilot.models import User


def upsert_user(session: Session, *, google_sub: str, email: str, display_name: str | None, avatar_url: str | None) -> User:
    """Called on every successful st.login() — creates the user on first sign-in,
    otherwise just bumps last_login_at."""
    user = session.scalar(select(User).where(User.google_sub == google_sub))
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            last_login_at=now,
        )
        session.add(user)
        session.flush()
    else:
        user.email = email
        user.display_name = display_name
        user.avatar_url = avatar_url
        user.last_login_at = now
    return user


def get_user_by_google_sub(session: Session, google_sub: str) -> User | None:
    return session.scalar(select(User).where(User.google_sub == google_sub))
