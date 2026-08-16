from research_copilot.sequencing import (
    STAGE_CURRENT,
    STAGE_FOUNDATIONAL,
    STAGE_REVIEW,
    in_set_citation_counts,
    sequence_reading_plan,
)

ATTENTION = {
    "id": "W_attention",
    "cited_by_count": 100_000,
    "publication_year": 2017,
    "referenced_works": ["W_seq2seq"],
}
SEQ2SEQ = {
    "id": "W_seq2seq",
    "cited_by_count": 20_000,
    "publication_year": 2014,
    "referenced_works": [],
}
NICHE_2023 = {
    "id": "W_niche",
    "cited_by_count": 50,
    "publication_year": 2023,
    "referenced_works": ["W_attention"],
}


def test_in_set_citation_counts():
    counts = in_set_citation_counts([ATTENTION, SEQ2SEQ, NICHE_2023])
    assert counts == {"W_attention": 1, "W_seq2seq": 1, "W_niche": 0}


def test_matches_the_worked_example_from_the_brief():
    """Attention Is All You Need -> Seq2Seq baseline -> a 2023 application:
    exactly the example given when the sequencing algorithm was specified."""
    plan = sequence_reading_plan([ATTENTION, SEQ2SEQ, NICHE_2023])
    ordered_ids = [p.paper_id for p in plan]
    stages = {p.paper_id: p.stage for p in plan}

    assert ordered_ids == ["W_attention", "W_seq2seq", "W_niche"]
    assert stages["W_attention"] == STAGE_REVIEW
    assert stages["W_seq2seq"] == STAGE_FOUNDATIONAL
    assert stages["W_niche"] == STAGE_CURRENT


def test_positions_are_sequential_and_unique():
    plan = sequence_reading_plan([ATTENTION, SEQ2SEQ, NICHE_2023])
    assert [p.position for p in plan] == [0, 1, 2]


def test_no_paper_is_dropped_or_duplicated():
    papers = [ATTENTION, SEQ2SEQ, NICHE_2023]
    plan = sequence_reading_plan(papers)
    assert {p.paper_id for p in plan} == {p["id"] for p in papers}


def test_empty_input():
    assert sequence_reading_plan([]) == []


def test_two_papers_falls_back_to_year_order():
    plan = sequence_reading_plan([ATTENTION, SEQ2SEQ])
    assert [p.paper_id for p in plan] == ["W_seq2seq", "W_attention"]


def test_complexity_score_only_breaks_review_ties():
    """Two equally-cited papers: the simpler one (lower complexity score) opens the plan."""
    dense = {"id": "A", "cited_by_count": 500, "publication_year": 2020, "referenced_works": []}
    simple = {"id": "B", "cited_by_count": 500, "publication_year": 2020, "referenced_works": []}
    third = {"id": "C", "cited_by_count": 10, "publication_year": 2021, "referenced_works": []}

    plan = sequence_reading_plan([dense, simple, third], complexity_scores={"A": 0.9, "B": 0.1})
    assert plan[0].paper_id == "B"
