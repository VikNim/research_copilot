"""Proves the app's actual repository functions work correctly under a
least-privilege database role (app_user: SELECT/INSERT/UPDATE/DELETE only, no
DDL) — not just that raw SQL happens to succeed. Schema creation (init_db) is
a separate, higher-privilege operation by design; this file never calls it.

Requires the local `app_user` role to exist (see project memory / the GRANT
script this session set up) — skipped automatically otherwise, same pattern
as requires_db/requires_fm_api.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from research_copilot.repositories import collections as collections_repo
from research_copilot.repositories import notes as notes_repo
from research_copilot.repositories import papers as papers_repo
from research_copilot.repositories import progress as progress_repo
from research_copilot.repositories import users as users_repo

APP_USER_URL = "postgresql+psycopg://app_user:local_dev_only_not_used_in_prod@localhost:5432/research_copilot_dev"

requires_app_user_role = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="local Postgres not configured for this session"
)


@pytest.fixture()
def app_user_session():
    engine = create_engine(APP_USER_URL, pool_pre_ping=True)
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
        engine.dispose()


@requires_app_user_role
def test_normal_app_operations_work_under_least_privilege_role(app_user_session):
    """Every repository function the app actually calls at runtime, exercised
    end to end under the restricted role — not the owner role every other
    test uses. If this fails, the app would break in production against a
    correctly-locked-down Lakebase connection."""
    session = app_user_session
    user = users_repo.upsert_user(
        session, google_sub="least-priv-test", email="lp@example.com", display_name="LP", avatar_url=None
    )
    paper = papers_repo.upsert_paper(session, {
        "id": "WLP1", "doi": None, "title": "Least Privilege Test Paper", "abstract": "test",
        "publication_year": 2023, "venue": None, "oa_status": None, "oa_pdf_url": None,
        "cited_by_count": 1, "topics": [], "referenced_works": [], "authors": [], "openalex_raw": {},
    })
    collection = collections_repo.create_collection(session, user_id=user.id, name="LP Collection")
    collections_repo.add_paper(session, collection_id=collection.id, paper_id=paper.id)
    progress_repo.set_status(session, user_id=user.id, paper_id=paper.id, status="in_progress", collection_id=collection.id)
    notes_repo.add_note(session, user_id=user.id, paper_id=paper.id, content="a note")

    papers_in_collection = collections_repo.list_papers_in_collection(session, collection.id)
    assert [p.id for p in papers_in_collection] == ["WLP1"]


@requires_app_user_role
def test_least_privilege_role_cannot_do_ddl(app_user_session):
    """The flip side — this role must NOT be able to alter schema. If this
    test fails (no exception raised), the "least privilege" claim is false."""
    with pytest.raises(ProgrammingError):
        app_user_session.execute(text("ALTER TABLE users ADD COLUMN hacked BOOLEAN"))
        app_user_session.flush()
