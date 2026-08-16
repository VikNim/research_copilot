"""Reading-plan sequencing: turns an unordered set of papers into the
Review -> Foundational -> Current order described in the blueprint.

Pure Python, no network/DB/LLM calls — the `complexity_scores` hook lets the
agent (agent.py) inject an LLM-scored jargon-density signal per paper without
this module needing to know how that score was produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Paper = dict[str, Any]

STAGE_REVIEW = "review"
STAGE_FOUNDATIONAL = "foundational"
STAGE_CURRENT = "current"


@dataclass(frozen=True)
class SequencedPaper:
    paper_id: str
    position: int
    stage: str
    rationale: str


def in_set_citation_counts(papers: list[Paper]) -> dict[str, int]:
    """For each paper, how many *other papers in this set* cite it.
    A high count signals it's foundational relative to the rest of the set."""
    counts = {p["id"]: 0 for p in papers}
    ids = set(counts)
    for paper in papers:
        for ref_id in paper.get("referenced_works", []) or []:
            if ref_id in ids and ref_id != paper["id"]:
                counts[ref_id] += 1
    return counts


def sequence_reading_plan(
    papers: list[Paper],
    complexity_scores: dict[str, float] | None = None,
) -> list[SequencedPaper]:
    """Order papers: highest-authority entry point first (Review), then older
    heavily-in-set-cited work (Foundational), then the rest by recency (Current).

    `complexity_scores` (optional, 0=simple .. 1=dense) only breaks ties on
    which paper opens the plan — it doesn't override the citation/date signal.
    """
    if not papers:
        return []

    complexity_scores = complexity_scores or {}
    by_id = {p["id"]: p for p in papers}

    if len(papers) <= 2:
        ordered = sorted(papers, key=lambda p: (p.get("publication_year") or 0, p["id"]))
        return [
            SequencedPaper(p["id"], i, STAGE_CURRENT, "Too few papers to stage — ordered by year.")
            for i, p in enumerate(ordered)
        ]

    in_set_counts = in_set_citation_counts(papers)

    def review_key(p: Paper) -> tuple:
        # highest overall citation count wins; a lower complexity score breaks ties
        return (-(p.get("cited_by_count") or 0), complexity_scores.get(p["id"], 0.5))

    review_paper = min(papers, key=review_key)
    remaining = [p for p in papers if p["id"] != review_paper["id"]]

    foundational = sorted(
        (p for p in remaining if in_set_counts.get(p["id"], 0) > 0),
        key=lambda p: (p.get("publication_year") or 0, -in_set_counts.get(p["id"], 0)),
    )
    foundational_ids = {p["id"] for p in foundational}

    current = sorted(
        (p for p in remaining if p["id"] not in foundational_ids),
        key=lambda p: (p.get("publication_year") or 0, p["id"]),
    )

    result: list[SequencedPaper] = []
    result.append(
        SequencedPaper(
            review_paper["id"],
            0,
            STAGE_REVIEW,
            f"Highest-cited entry point ({review_paper.get('cited_by_count', 0)} citations) — start here.",
        )
    )
    for i, p in enumerate(foundational, start=1):
        cited_by_n = in_set_counts.get(p["id"], 0)
        result.append(
            SequencedPaper(
                p["id"],
                i,
                STAGE_FOUNDATIONAL,
                f"Referenced by {cited_by_n} other paper(s) in this set — foundational to the rest.",
            )
        )
    for i, p in enumerate(current, start=len(result)):
        result.append(
            SequencedPaper(
                p["id"],
                i,
                STAGE_CURRENT,
                f"Recent ({p.get('publication_year', '?')}), builds on the foundation above.",
            )
        )

    assert {r.paper_id for r in result} == set(by_id), "sequencing dropped or duplicated a paper"
    return result
