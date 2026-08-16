"""DB-backed tests run against DATABASE_URL (this session's local Postgres 17 +
pgvector) inside a transaction that's always rolled back, so the dev database
stays empty between runs."""

import os

import pytest
from sqlalchemy.orm import Session

from research_copilot.db import get_engine, init_db

requires_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


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
