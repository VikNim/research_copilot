"""Live test of the Study Buddy discovery + validated-explanation pipeline —
real OpenAlex, real embeddings, real Claude Haiku 4.5, real Flesch-Kincaid
scoring, real faithfulness judge. Uses the spec's own example goal."""

from __future__ import annotations

from research_copilot import study_buddy
from research_copilot.db import session_scope

from conftest import requires_db, requires_fm_api

GOAL = "I want to understand how CRISPR works"


@requires_db
@requires_fm_api
def test_discover_entry_points_returns_relevant_papers():
    with session_scope() as session:
        entry_points = study_buddy.discover_entry_points(session, GOAL, candidate_pool_size=15, max_entry_points=2)

    assert 1 <= len(entry_points) <= 2
    for ep in entry_points:
        assert ep.title
        assert ep.reason


@requires_db
@requires_fm_api
def test_layer1_explanation_converges_on_readability_and_faithfulness():
    with session_scope() as session:
        entry_points = study_buddy.discover_entry_points(session, GOAL, candidate_pool_size=15, max_entry_points=2)
    evidence = [ep.abstract for ep in entry_points if ep.abstract]
    assert evidence, "need at least one entry-point abstract to explain from"

    result = study_buddy.generate_validated_explanation("How CRISPR works", evidence, layer=1, max_attempts=4)

    # the gate is real (proven to fail on attempt 1 in live testing) — this asserts
    # the *loop* eventually gets there, not that one shot always succeeds
    assert not result.gave_up, f"never converged: {result.history}"
    assert result.reading_grade <= study_buddy.READABILITY_GRADE_CEILING
    assert result.faithful
    assert len(result.content) > 0
