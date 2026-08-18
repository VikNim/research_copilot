"""Exercises the real schema against this session's local Postgres 17 + pgvector —
not just a read of the DDL. Skipped automatically if DATABASE_URL isn't set."""

import os
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from research_copilot.config import EMBEDDING_DIM
from research_copilot.models import Note
from research_copilot.repositories import collections as collections_repo
from research_copilot.repositories import goals as goals_repo
from research_copilot.repositories import notes as notes_repo
from research_copilot.repositories import papers as papers_repo
from research_copilot.repositories import progress as progress_repo
from research_copilot.repositories import users as users_repo

requires_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _one_hot(index: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[index] = 1.0
    return v


def _fake_paper(paper_id: str, title: str, year: int, citations: int, refs: list[str] | None = None) -> dict:
    return {
        "id": paper_id,
        "doi": None,
        "title": title,
        "abstract": f"Abstract for {title}",
        "publication_year": year,
        "venue": "Test Venue",
        "oa_status": "green",
        "oa_pdf_url": None,
        "cited_by_count": citations,
        "topics": [],
        "referenced_works": refs or [],
        "authors": [{"id": f"A_{paper_id}", "display_name": f"Author of {paper_id}", "orcid": None, "institution_name": None}],
        "openalex_raw": {"referenced_works": [f"https://openalex.org/{r}" for r in (refs or [])]},
    }


@requires_db
def test_user_goal_roundtrip_with_embedding(db_session):
    user = users_repo.upsert_user(db_session, google_sub="sub-1", email="a@example.com", display_name="A", avatar_url=None)
    goal = goals_repo.create_goal(db_session, user_id=user.id, title="Learn transformers", embedding=_one_hot(0))
    db_session.flush()

    fetched = goals_repo.get_goal(db_session, goal.id)
    assert fetched is not None
    assert fetched.title == "Learn transformers"
    assert len(fetched.embedding) == EMBEDDING_DIM


@requires_db
def test_upsert_user_is_idempotent_on_google_sub(db_session):
    u1 = users_repo.upsert_user(db_session, google_sub="sub-2", email="b@example.com", display_name="B", avatar_url=None)
    u2 = users_repo.upsert_user(db_session, google_sub="sub-2", email="b-new@example.com", display_name="B2", avatar_url=None)
    assert u1.id == u2.id
    assert u2.email == "b-new@example.com"


@requires_db
def test_collection_paper_order_and_progress_and_next(db_session):
    user = users_repo.upsert_user(db_session, google_sub="sub-3", email="c@example.com", display_name="C", avatar_url=None)
    p1 = papers_repo.upsert_paper(db_session, _fake_paper("W1", "Foundational Paper", 2015, 500))
    p2 = papers_repo.upsert_paper(db_session, _fake_paper("W2", "Review Paper", 2020, 5000, refs=["W1"]))
    collection = collections_repo.create_collection(db_session, user_id=user.id, name="Test Collection")

    collections_repo.add_paper(db_session, collection_id=collection.id, paper_id=p2.id, position=0)
    collections_repo.add_paper(db_session, collection_id=collection.id, paper_id=p1.id, position=1)

    ordered = collections_repo.list_papers_in_collection(db_session, collection.id)
    assert [p.id for p in ordered] == ["W2", "W1"]

    # nothing read yet -> recommend the first paper in reading order
    next_id = progress_repo.recommend_next(db_session, user_id=user.id, collection_id=collection.id, ordered_paper_ids=[p.id for p in ordered])
    assert next_id == "W2"

    progress_repo.set_status(db_session, user_id=user.id, paper_id="W2", status="done", collection_id=collection.id)
    next_id = progress_repo.recommend_next(db_session, user_id=user.id, collection_id=collection.id, ordered_paper_ids=[p.id for p in ordered])
    assert next_id == "W1"


@requires_db
def test_set_status_keeps_progress_pct_consistent(db_session):
    # a real collection_id — matches every actual call site in the app; see
    # set_status's docstring for why collection_id=None doesn't upsert cleanly.
    user = users_repo.upsert_user(db_session, google_sub="sub-6", email="f@example.com", display_name="F", avatar_url=None)
    papers_repo.upsert_paper(db_session, _fake_paper("WP1", "Status Paper", 2022, 1))
    collection = collections_repo.create_collection(db_session, user_id=user.id, name="Status Test Collection")

    p = progress_repo.set_status(db_session, user_id=user.id, paper_id="WP1", status="in_progress", collection_id=collection.id)
    assert p.progress_pct == 50
    assert p.started_at is not None

    p = progress_repo.set_status(db_session, user_id=user.id, paper_id="WP1", status="done", collection_id=collection.id)
    assert p.progress_pct == 100
    assert p.completed_at is not None
    assert p.started_at is not None  # preserved from the first call, not cleared

    with pytest.raises(ValueError):
        progress_repo.set_status(db_session, user_id=user.id, paper_id="WP1", status="halfway", collection_id=collection.id)


@requires_db
def test_semantic_search_orders_by_cosine_distance(db_session):
    papers_repo.upsert_paper(db_session, _fake_paper("WV1", "Vector One", 2020, 10))
    papers_repo.upsert_paper(db_session, _fake_paper("WV2", "Vector Two", 2020, 10))
    papers_repo.upsert_paper(db_session, _fake_paper("WV3", "Vector Three", 2020, 10))

    db_session.get(papers_repo.Paper, "WV1").embedding = _one_hot(0)
    db_session.get(papers_repo.Paper, "WV2").embedding = _one_hot(1)
    db_session.get(papers_repo.Paper, "WV3").embedding = _one_hot(2)
    db_session.flush()

    nearest = papers_repo.semantic_search(db_session, query_embedding=_one_hot(1), limit=3)
    assert nearest[0].id == "WV2"  # identical vector -> smallest cosine distance


@requires_db
def test_notes_require_a_scope_at_the_db_level(db_session):
    user = users_repo.upsert_user(db_session, google_sub="sub-4", email="d@example.com", display_name="D", avatar_url=None)
    unscoped = Note(id=uuid.uuid4(), user_id=user.id, paper_id=None, collection_id=None, content="orphan note")
    db_session.add(unscoped)
    with pytest.raises(IntegrityError):
        db_session.flush()


@requires_db
def test_notes_two_scopes_paper_and_collection(db_session):
    user = users_repo.upsert_user(db_session, google_sub="sub-5", email="e@example.com", display_name="E", avatar_url=None)
    paper = papers_repo.upsert_paper(db_session, _fake_paper("WN1", "Notable Paper", 2021, 1))
    collection = collections_repo.create_collection(db_session, user_id=user.id, name="Notes Test")

    notes_repo.add_note(db_session, user_id=user.id, paper_id=paper.id, content="about this paper")
    notes_repo.add_note(db_session, user_id=user.id, collection_id=collection.id, content="about the topic")

    paper_notes = notes_repo.list_for_paper(db_session, user_id=user.id, paper_id=paper.id)
    collection_notes = notes_repo.list_for_collection(db_session, user_id=user.id, collection_id=collection.id)

    assert [n.content for n in paper_notes] == ["about this paper"]
    assert [n.content for n in collection_notes] == ["about the topic"]


@requires_db
def test_ai_summary_notes_are_labeled_and_detectable(db_session):
    """A saved summary needs to read as its own distinct thing, not an
    anonymous note that happens to repeat the paper's content — and a
    regular, manually-typed note must not be mistaken for one."""
    user = users_repo.upsert_user(db_session, google_sub="sub-8", email="h@example.com", display_name="H", avatar_url=None)
    paper = papers_repo.upsert_paper(db_session, _fake_paper("WSUM1", "Summary Label Paper", 2022, 1))

    assert not notes_repo.has_ai_summary(db_session, user_id=user.id, paper_id=paper.id)

    notes_repo.add_note(
        db_session, user_id=user.id, paper_id=paper.id,
        content=notes_repo.format_summary_note("This paper shows X causes Y."),
    )
    notes_repo.add_note(db_session, user_id=user.id, paper_id=paper.id, content="my own manual note")

    assert notes_repo.has_ai_summary(db_session, user_id=user.id, paper_id=paper.id)
    contents = [n.content for n in notes_repo.list_for_paper(db_session, user_id=user.id, paper_id=paper.id)]
    flagged = [c.startswith(f"**{notes_repo.AI_SUMMARY_LABEL}**") for c in contents]
    assert sorted(flagged) == [False, True]  # exactly one of the two notes is the summary


@requires_db
def test_search_creates_learning_goal_and_links_to_saved_collection(db_session):
    """Closes a real gap: learning_goals existed in the schema since day one but
    no UI flow ever wrote to it. Screen 1's search is the actual "state a
    learning goal in plain language" moment — this is what get_or_create_goal
    (called from Home.py on every valid search) plus Save Collection passing
    learning_goal_id through are meant to produce."""
    user = users_repo.upsert_user(db_session, google_sub="sub-7", email="g@example.com", display_name="G", avatar_url=None)

    goal1 = goals_repo.get_or_create_goal(db_session, user_id=user.id, title="Understand attention mechanisms")
    goal2 = goals_repo.get_or_create_goal(db_session, user_id=user.id, title="understand attention mechanisms  ")
    assert goal1.id == goal2.id  # repeat/near-identical search reuses the goal, doesn't fork one

    collection = collections_repo.create_collection(
        db_session, user_id=user.id, name="Attention Papers", learning_goal_id=goal1.id
    )
    assert collection.learning_goal_id == goal1.id
    assert collection.learning_goal.title == "Understand attention mechanisms"
    assert [g.id for g in goals_repo.list_goals_for_user(db_session, user.id)] == [goal1.id]
