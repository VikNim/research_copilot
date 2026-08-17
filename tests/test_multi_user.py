"""Simulates two concurrent users touching the same paper and the same collection
name, to catch cross-user data leaks before they show up as a real bug with two
real logged-in browser tabs. Can't drive two actual browser sessions in this
environment — st.session_state isolation is Streamlit's own guarantee, audited
separately (see project memory) — but every isolation guarantee that depends on
*our* code (user_id scoping in every repo query) is exercised for real here."""

from __future__ import annotations

from research_copilot.repositories import collections as collections_repo
from research_copilot.repositories import notes as notes_repo
from research_copilot.repositories import papers as papers_repo
from research_copilot.repositories import progress as progress_repo
from research_copilot.repositories import users as users_repo

from conftest import requires_db


def _fake_paper(oa_id: str, title: str) -> dict:
    return {
        "id": oa_id, "doi": None, "title": title, "abstract": f"Abstract for {title}.",
        "publication_year": 2023, "venue": "Test Venue", "oa_status": "gold",
        "oa_pdf_url": None, "cited_by_count": 10, "topics": [], "referenced_works": [],
        "authors": [], "openalex_raw": {},
    }


@requires_db
def test_two_users_same_paper_same_collection_name_stay_isolated(db_session):
    alice = users_repo.upsert_user(db_session, google_sub="alice-mu", email="alice@example.com", display_name="Alice", avatar_url=None)
    bob = users_repo.upsert_user(db_session, google_sub="bob-mu", email="bob@example.com", display_name="Bob", avatar_url=None)

    # both cache-through the *same* OpenAlex paper independently — papers are a
    # shared cache by design (keyed by OpenAlex id), this must not create per-user duplicates
    shared_paper = papers_repo.upsert_paper(db_session, _fake_paper("WMU1", "Shared Paper"))
    again = papers_repo.upsert_paper(db_session, _fake_paper("WMU1", "Shared Paper"))
    assert shared_paper.id == again.id

    # both create a collection with the identical name — must not collide or merge
    alice_collection = collections_repo.create_collection(db_session, user_id=alice.id, name="Reading List")
    bob_collection = collections_repo.create_collection(db_session, user_id=bob.id, name="Reading List")
    assert alice_collection.id != bob_collection.id

    collections_repo.add_paper(db_session, collection_id=alice_collection.id, paper_id=shared_paper.id)
    collections_repo.add_paper(db_session, collection_id=bob_collection.id, paper_id=shared_paper.id)

    # find_by_name (the duplicate-collection check) must be scoped per user
    alice_match = collections_repo.find_by_name(db_session, user_id=alice.id, name="Reading List")
    bob_match = collections_repo.find_by_name(db_session, user_id=bob.id, name="Reading List")
    assert alice_match.id == alice_collection.id
    assert bob_match.id == bob_collection.id

    # each only sees their own collection in their own list
    assert [c.id for c in collections_repo.list_collections_for_user(db_session, alice.id)] == [alice_collection.id]
    assert [c.id for c in collections_repo.list_collections_for_user(db_session, bob.id)] == [bob_collection.id]

    # progress on the *same paper* diverges independently per user
    progress_repo.set_status(db_session, user_id=alice.id, paper_id=shared_paper.id, status="done", collection_id=alice_collection.id)
    progress_repo.set_status(db_session, user_id=bob.id, paper_id=shared_paper.id, status="not_started", collection_id=bob_collection.id)
    alice_progress = progress_repo.list_for_collection(db_session, user_id=alice.id, collection_id=alice_collection.id)
    bob_progress = progress_repo.list_for_collection(db_session, user_id=bob.id, collection_id=bob_collection.id)
    assert alice_progress[shared_paper.id].status == "done"
    assert bob_progress[shared_paper.id].status == "not_started"

    # notes on the same paper are private per user, not shared just because the paper is
    notes_repo.add_note(db_session, user_id=alice.id, paper_id=shared_paper.id, content="Alice's private note")
    notes_repo.add_note(db_session, user_id=bob.id, paper_id=shared_paper.id, content="Bob's private note")
    alice_notes = notes_repo.list_for_paper(db_session, user_id=alice.id, paper_id=shared_paper.id)
    bob_notes = notes_repo.list_for_paper(db_session, user_id=bob.id, paper_id=shared_paper.id)
    assert [n.content for n in alice_notes] == ["Alice's private note"]
    assert [n.content for n in bob_notes] == ["Bob's private note"]
