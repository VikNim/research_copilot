"""Ties embeddings.py (the Databricks FM API call) to papers_repo (storage):
embeds on demand for papers that don't have a vector yet, then ranks a candidate
set by meaning rather than keyword match. This is the first real caller of the
embedding pipeline — it existed but nothing invoked it until now.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from research_copilot import embeddings
from research_copilot.repositories import papers as papers_repo


def ensure_paper_embeddings(session: Session, paper_ids: list[str]) -> None:
    """Embeds any papers in the given set that don't have a vector yet (skips
    ones with no abstract — nothing to embed). Lazy and on-demand, not run for
    every search, only when semantic ranking is actually requested."""
    missing = papers_repo.papers_missing_embeddings(session, paper_ids)
    if not missing:
        return
    vectors = embeddings.embed_texts([p.abstract for p in missing])
    for paper, vector in zip(missing, vectors):
        paper.embedding = vector
    session.flush()


def semantic_rank(session: Session, paper_ids: list[str], query: str) -> list[str]:
    """Returns `paper_ids` reordered by semantic similarity to `query`. Papers
    that couldn't be embedded (no abstract) keep their relative order at the end."""
    ensure_paper_embeddings(session, paper_ids)
    query_vector = embeddings.embed_text(query)
    ranked = papers_repo.rank_by_similarity(session, paper_ids, query_vector)
    ranked_ids = [p.id for p in ranked]
    remaining = [pid for pid in paper_ids if pid not in ranked_ids]
    return ranked_ids + remaining
