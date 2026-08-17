"""Live test of the actual tool-calling loop — real OpenAlex data, real Claude
Haiku 4.5 call via Databricks FM APIs, real tool dispatch against the DB.
Everything else in the test suite exercises the tools individually; this is the
one test that proves the loop the model actually drives works end to end."""

from __future__ import annotations

from research_copilot import agent
from research_copilot.openalex_client import OpenAlexClient
from research_copilot.repositories import collections as collections_repo
from research_copilot.repositories import papers as papers_repo
from research_copilot.repositories import users as users_repo

from conftest import requires_db, requires_fm_api


@requires_db
@requires_fm_api
def test_agent_compares_collection_papers_with_citations(db_session):
    client = OpenAlexClient()
    found = client.search_works("transformer attention neural network", per_page=3)

    user = users_repo.upsert_user(
        db_session, google_sub="live-agent-test", email="agenttest@example.com",
        display_name="Agent Test", avatar_url=None,
    )
    collection = collections_repo.create_collection(db_session, user_id=user.id, name="Agent Live Test")
    for p in found:
        saved = papers_repo.upsert_paper(db_session, p)
        collections_repo.add_paper(db_session, collection_id=collection.id, paper_id=saved.id)

    result = agent.run_agent(
        db_session, user.id,
        "Compare these papers for me and tell me which one I should read first, with citations.",
        context_note=(
            f'The active collection_id is "{collection.id}" (name: "Agent Live Test"). '
            "Use it for any tool that takes a collection_id."
        ),
    )

    tool_calls_made = [
        tc["function"]["name"]
        for m in result if m.get("role") == "assistant" and m.get("tool_calls")
        for tc in m["tool_calls"]
    ]
    # the model must discover the collection's papers itself, not ask the user to re-list them
    assert "list_collection_papers" in tool_calls_made
    assert "retrieve_evidence" in tool_calls_made

    final = next(m for m in reversed(result) if m.get("role") == "assistant" and m.get("content"))
    paper_ids_seen = {p["id"] for p in found}
    # the final answer must actually reference real papers from the collection, not invented ones
    assert any(pid in final["content"] for pid in paper_ids_seen) or "Attention" in final["content"]
