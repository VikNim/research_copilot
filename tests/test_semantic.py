"""Live test — real OpenAlex results, real Databricks embeddings call, real
pgvector ranking. Skipped automatically when FM API isn't configured/logged in."""

from __future__ import annotations

from research_copilot import semantic
from research_copilot.openalex_client import OpenAlexClient
from research_copilot.repositories import papers as papers_repo

from conftest import requires_db, requires_fm_api


@requires_db
@requires_fm_api
def test_semantic_rank_separates_unrelated_topics(db_session):
    client = OpenAlexClient()
    transformer_papers = client.search_works("transformer attention neural network", per_page=3)
    climate_papers = client.search_works("climate change ocean acidification", per_page=3)
    mixed = transformer_papers + climate_papers

    for p in mixed:
        papers_repo.upsert_paper(db_session, p)
    ids = [p["id"] for p in mixed]

    ranked_ids = semantic.semantic_rank(db_session, ids, "deep learning attention mechanisms for sequence modeling")

    transformer_ids = {p["id"] for p in transformer_papers}
    climate_ids = {p["id"] for p in climate_papers}
    top_half = set(ranked_ids[: len(transformer_papers)])

    # the transformer papers should dominate the top of the ranking for a transformer-ish query
    assert len(top_half & transformer_ids) >= 2
    assert len(top_half & climate_ids) <= 1


@requires_db
@requires_fm_api
def test_ensure_paper_embeddings_is_idempotent(db_session):
    client = OpenAlexClient()
    [paper] = client.search_works("graph neural networks", per_page=1)
    papers_repo.upsert_paper(db_session, paper)

    semantic.ensure_paper_embeddings(db_session, [paper["id"]])
    saved = papers_repo.get_paper(db_session, paper["id"])
    assert saved.embedding is not None
    first_vector = list(saved.embedding)

    # second call should not re-embed (no API call, vector unchanged)
    semantic.ensure_paper_embeddings(db_session, [paper["id"]])
    saved_again = papers_repo.get_paper(db_session, paper["id"])
    assert list(saved_again.embedding) == first_vector
