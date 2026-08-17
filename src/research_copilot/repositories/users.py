from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from research_copilot.models import User


def upsert_user(session: Session, *, google_sub: str, email: str, display_name: str | None, avatar_url: str | None) -> User:
    """Called on every successful st.login() — creates the user on first sign-in,
    otherwise just bumps last_login_at. Atomic upsert (not check-then-insert):
    two tabs completing login near-simultaneously would otherwise race the same
    way concurrent paper caching did (see papers_repo)."""
    now = datetime.now(timezone.utc)
    stmt = pg_insert(User).values(
        google_sub=google_sub, email=email, display_name=display_name,
        avatar_url=avatar_url, last_login_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[User.google_sub],
        set_={
            "email": stmt.excluded.email,
            "display_name": stmt.excluded.display_name,
            "avatar_url": stmt.excluded.avatar_url,
            "last_login_at": stmt.excluded.last_login_at,
        },
    )
    session.execute(stmt)
    session.flush()
    # populate_existing: a raw Core write doesn't refresh an already-loaded ORM
    # instance of this row in the identity map — without this, a second upsert
    # in the same session would silently return the pre-update, stale object.
    return session.scalar(
        select(User).where(User.google_sub == google_sub).execution_options(populate_existing=True)
    )


def get_user_by_google_sub(session: Session, google_sub: str) -> User | None:
    return session.scalar(select(User).where(User.google_sub == google_sub))
