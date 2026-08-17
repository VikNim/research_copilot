"""DB-backed tests run against DATABASE_URL (this session's local Postgres 17 +
pgvector) inside a transaction that's always rolled back, so the dev database
stays empty between runs."""

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv(override=True)  # .env is the source of truth locally — don't let a stray shell export shadow it

from research_copilot.db import get_engine, init_db  # noqa: E402

requires_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
requires_fm_api = pytest.mark.skipif(
    not (os.environ.get("DATABRICKS_FM_BASE_URL") and os.environ.get("DATABRICKS_PROFILE")),
    reason="Databricks FM API not configured (needs a live `databricks auth login` session)",
)


@pytest.fixture(scope="session", autouse=True)
def _init_schema():
    # Skip when DATABASE_URL points at a least-privilege role (e.g. app_user on
    # Lakebase) that can't run DDL by design — schema there is migrated by hand
    # as the owner. Set SKIP_DB_INIT=1 in that case; local dev Postgres (where
    # the connecting role owns the schema) keeps auto-initializing as before.
    if os.environ.get("DATABASE_URL") and not os.environ.get("SKIP_DB_INIT"):
        init_db()


@pytest.fixture()
def db_session():
    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
