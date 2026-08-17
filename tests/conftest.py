"""DB-backed tests run against DATABASE_URL (this session's local Postgres 17 +
pgvector) inside a transaction that's always rolled back, so the dev database
stays empty between runs."""

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv()

from research_copilot.db import get_engine, init_db  # noqa: E402

requires_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
requires_fm_api = pytest.mark.skipif(
    not (os.environ.get("DATABRICKS_FM_BASE_URL") and os.environ.get("DATABRICKS_PROFILE")),
    reason="Databricks FM API not configured (needs a live `databricks auth login` session)",
)


@pytest.fixture(scope="session", autouse=True)
def _init_schema():
    if os.environ.get("DATABASE_URL"):
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
