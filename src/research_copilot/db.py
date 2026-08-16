"""Database engine setup.

Three paths, chosen by what's configured:
  - `DATABASE_URL` set -> plain Postgres connection (local dev, tests, this session's
    Homebrew-installed Postgres 17 + pgvector).
  - Lakebase via Databricks CLI profile or service principal -> a fresh short-lived OAuth
    database credential is minted on every new connection (`generate_database_credential`,
    confirmed against the real Databricks SDK and a real, live Lakebase instance — schema
    is already applied there). The CLI-profile path needs `databricks auth login` to have
    completed (interactive/browser-based, can't be done headlessly); until then it raises,
    same as if unconfigured.
  - Lakebase via a static pasted token (`LAKEBASE_STATIC_TOKEN`) -> manual escape hatch,
    good for about an hour, no auto-refresh. One-off checks only, not for the running app.

Either way, callers just get a SQLAlchemy engine/session and don't care which path it is.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from research_copilot.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


class DatabaseNotConfigured(RuntimeError):
    """Raised when neither DATABASE_URL nor Lakebase settings are present."""


def _build_lakebase_credential_creator(settings: Settings):
    """Mints a fresh Lakebase credential on every new connection — via the Databricks
    CLI's own OAuth profile if set, otherwise a service principal."""
    from databricks.sdk import WorkspaceClient

    def creator():
        import psycopg

        if settings.databricks_profile:
            w = WorkspaceClient(profile=settings.databricks_profile)
        else:
            w = WorkspaceClient(
                host=settings.databricks_host,
                client_id=settings.databricks_client_id,
                client_secret=settings.databricks_client_secret,
            )
        cred = w.database.generate_database_credential(
            instance_names=[settings.lakebase_instance_name],
        )
        return psycopg.connect(
            host=settings.lakebase_host,
            port=settings.lakebase_port,
            dbname=settings.lakebase_db_name,
            user=settings.lakebase_db_user,
            password=cred.token,
            sslmode="require",
        )

    return creator


def _build_lakebase_static_creator(settings: Settings):
    """Manual escape hatch: connects with a hand-pasted token as the password.
    Good for ~1hr, no refresh — fine for a one-off check, not the running app."""

    def creator():
        import psycopg

        return psycopg.connect(
            host=settings.lakebase_host,
            port=settings.lakebase_port,
            dbname=settings.lakebase_db_name,
            user=settings.lakebase_db_user,
            password=settings.lakebase_static_token,
            sslmode="require",
        )

    return creator


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    settings = settings or get_settings()

    if settings.has_local_db:
        logger.info("Connecting via DATABASE_URL (local/dev path)")
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    elif settings.has_lakebase_credential_flow:
        logger.info("Connecting to Lakebase via minted OAuth credential")
        _engine = create_engine(
            "postgresql+psycopg://",
            creator=_build_lakebase_credential_creator(settings),
            pool_pre_ping=True,
            pool_recycle=1800,  # credentials expire at 60 min; refresh well before that
        )
    elif settings.has_lakebase_static_token:
        logger.warning("Connecting to Lakebase with a static pasted token — expires in ~1hr, no refresh")
        _engine = create_engine(
            "postgresql+psycopg://",
            creator=_build_lakebase_static_creator(settings),
            pool_pre_ping=True,
        )
    else:
        raise DatabaseNotConfigured(
            "Set DATABASE_URL for local dev; DATABRICKS_PROFILE (after `databricks auth "
            "login`) or DATABRICKS_CLIENT_ID/_SECRET plus LAKEBASE_INSTANCE_NAME/_HOST/"
            "_DB_USER for Lakebase; or LAKEBASE_STATIC_TOKEN for a one-off manual check."
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(settings), expire_on_commit=False)
    return _SessionFactory


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(settings: Settings | None = None) -> None:
    """Creates the pgvector extension and all tables. Idempotent."""
    from sqlalchemy import text

    from research_copilot.models import Base

    engine = get_engine(settings)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
