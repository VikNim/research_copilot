"""Security-focused tests for database operations: cross-user authorization
(IDOR), SQL injection resistance, and transaction integrity under partial
failure. Each test here corresponds to a real, live-verified finding from a
security review of the agent's tool-calling loop — not hypothetical checks."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from research_copilot import agent
from research_copilot.repositories import collections as collections_repo
from research_copilot.repositories import notes as notes_repo
from research_copilot.repositories import papers as papers_repo
from research_copilot.repositories import users as users_repo

from conftest import requires_db


@requires_db
def test_get_owned_collection_rejects_other_users_collection(db_session):
    owner = users_repo.upsert_user(db_session, google_sub="idor-owner", email="owner@example.com", display_name="Owner", avatar_url=None)
    attacker = users_repo.upsert_user(db_session, google_sub="idor-attacker", email="attacker@example.com", display_name="Attacker", avatar_url=None)
    collection = collections_repo.create_collection(db_session, user_id=owner.id, name="Owner's Private Collection")

    # the owner can fetch their own collection
    assert collections_repo.get_owned_collection(db_session, collection.id, owner.id) is not None
    # the attacker cannot, even with the exact correct id
    assert collections_repo.get_owned_collection(db_session, collection.id, attacker.id) is None
    # a nonexistent id behaves identically — no way to distinguish "not yours" from "doesn't exist"
    assert collections_repo.get_owned_collection(db_session, uuid.uuid4(), attacker.id) is None


@requires_db
def test_agent_tools_reject_collection_ids_the_user_does_not_own(db_session):
    """The agent's tool-calling loop takes collection_id as a plain string
    argument from the model — which is ultimately user-influenced input (a
    user could type someone else's id directly into the chat). Every tool
    that accepts a collection_id must check ownership, not just the UI paths
    that usually supply a pre-verified one."""
    owner = users_repo.upsert_user(db_session, google_sub="idor-owner-2", email="owner2@example.com", display_name="Owner2", avatar_url=None)
    attacker = users_repo.upsert_user(db_session, google_sub="idor-attacker-2", email="attacker2@example.com", display_name="Attacker2", avatar_url=None)
    collection = collections_repo.create_collection(db_session, user_id=owner.id, name="Owner2's Collection")
    papers_repo.upsert_paper(db_session, {
        "id": "WSEC1", "doi": None, "title": "Security Test Paper", "abstract": "test",
        "publication_year": 2023, "venue": None, "oa_status": None, "oa_pdf_url": None,
        "cited_by_count": 1, "topics": [], "referenced_works": [], "authors": [], "openalex_raw": {},
    })

    for tool_name, args in [
        ("list_collection_papers", {"collection_id": str(collection.id)}),
        ("generate_reading_plan", {"collection_id": str(collection.id)}),
        ("add_to_collection", {"collection_id": str(collection.id), "paper_id": "WSEC1"}),
        ("recommend_next", {"collection_id": str(collection.id)}),
    ]:
        # _dispatch raises directly — run_agent's loop is what converts this to a
        # clean {"error": ...} for the model; calling _dispatch itself here is the
        # more precise check that the *rejection* is really happening.
        with pytest.raises(agent.ToolAuthorizationError):
            agent._dispatch(db_session, attacker.id, tool_name, args)

        # the same call succeeds for the actual owner (proves the rejection above
        # is really an ownership check, not the tool just being broken generally)
        owner_result = agent._dispatch(db_session, owner.id, tool_name, args)
        assert "error" not in owner_result, f"{tool_name} incorrectly rejected the real owner: {owner_result}"


@requires_db
def test_oversized_text_is_rejected_at_the_database_level(db_session):
    """Defense in depth: even if an app-level guard (Streamlit's max_chars) were
    bypassed or missing on some future write path, the DB itself refuses an
    unbounded string rather than storing it."""
    user = users_repo.upsert_user(db_session, google_sub="length-test", email="len@example.com", display_name="Len", avatar_url=None)

    # SAVEPOINT per attempt, not a plain db_session.rollback() — a bare rollback()
    # here would roll back the *whole* test transaction (including the user insert
    # above), the exact same transaction-scope mistake test_security.py's own
    # transaction-poisoning test exists to catch in the real agent code.
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            collections_repo.create_collection(db_session, user_id=user.id, name="x" * 301)

    collection = collections_repo.create_collection(db_session, user_id=user.id, name="Length Test Collection")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            notes_repo.add_note(db_session, user_id=user.id, collection_id=collection.id, content="x" * 20001)


@requires_db
def test_sql_injection_payloads_are_stored_as_literal_data(db_session):
    """SQLAlchemy parameterizes every query in this codebase — no raw string
    interpolation into SQL. Proves it rather than just asserting it by code
    review: classic injection payloads go in as user content and come back
    out unchanged, with the schema intact."""
    user = users_repo.upsert_user(db_session, google_sub="injection-test", email="inj@example.com", display_name="Inj", avatar_url=None)
    payload = "'; DROP TABLE users; --"

    collection = collections_repo.create_collection(db_session, user_id=user.id, name=payload)
    assert collection.name == payload  # stored as literal text, not executed

    note = notes_repo.add_note(db_session, user_id=user.id, collection_id=collection.id, content=payload)
    assert note.content == payload

    # the users table must still exist and be queryable — the payload never ran as SQL
    still_there = users_repo.get_user_by_google_sub(db_session, "injection-test")
    assert still_there is not None


@requires_db
def test_failed_tool_call_does_not_break_subsequent_tool_calls_same_turn(db_session):
    """Regression test for a real bug found live: a foreign-key violation from
    one tool call (e.g. a paper_id that doesn't exist) used to poison the whole
    Postgres transaction, so every *subsequent* tool call in the same agent
    turn failed too, with a confusing "transaction aborted" error instead of
    its own real result. Fixed with a SAVEPOINT per tool call in run_agent's
    loop; this test exercises the same pattern directly against _dispatch."""
    user = users_repo.upsert_user(db_session, google_sub="txn-poison-regression", email="txn@example.com", display_name="Txn", avatar_url=None)
    collection = collections_repo.create_collection(db_session, user_id=user.id, name="Txn Regression Test")

    def dispatch_like_run_agent(name, args):
        try:
            with db_session.begin_nested():
                return agent._dispatch(db_session, user.id, name, args)
        except Exception as exc:  # noqa: BLE001 - mirrors run_agent's own handling
            return {"error": str(exc)}

    bad_result = dispatch_like_run_agent(
        "add_to_collection", {"collection_id": str(collection.id), "paper_id": "W_DOES_NOT_EXIST"}
    )
    assert "error" in bad_result

    good_result = dispatch_like_run_agent("list_collection_papers", {"collection_id": str(collection.id)})
    assert "error" not in good_result, f"transaction was poisoned by the prior failure: {good_result}"
