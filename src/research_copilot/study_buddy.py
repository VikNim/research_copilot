"""Study Buddy: a second, separate conversational mode (see models.py's Study
Buddy section) — invisible discovery, layered explanations, comprehension
checks. Built as a standalone pipeline module so each stage is independently
testable, same discipline as semantic.py and agent.py.

Reuses openalex_client, semantic.py, and llm.py as-is — nothing about paper
fetching or embedding changes for this mode, only what's built on top.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import textstat
from sqlalchemy.orm import Session

from research_copilot import llm, semantic
from research_copilot.openalex_client import OpenAlexClient
from research_copilot.repositories import papers as papers_repo

LAYER_RULES = {
    1: (
        "ELI5. One paragraph. Only everyday analogies (kitchen, playground, nature, "
        "toys) — zero technical terms. Understandable to a 5-year-old, but never "
        "childish or condescending to an adult reading it."
    ),
    2: (
        "Curious adult. 3-5 sentences. You may introduce 1-2 key technical terms, "
        "but define each in plain language immediately when first used."
    ),
    3: (
        "Ready to go deeper. Explain the actual mechanism/finding using proper "
        "technical terms, each defined on first use. Include what's still "
        "uncertain or debated, if the source says so."
    ),
}


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")
    return json.loads(match.group(0))


@dataclass
class EntryPointPaper:
    paper_id: str
    title: str
    abstract: str
    reason: str


def discover_entry_points(
    session: Session, learning_goal: str, candidate_pool_size: int = 25, max_entry_points: int = 3
) -> list[EntryPointPaper]:
    """Stage 0 (OpenAlex, broad net) -> Stage 1 (cheap semantic rank) -> Stage 2
    (LLM rerank + filter + entry-point selection). Never surfaced raw — this
    returns only the 1-3 papers chosen to actually start teaching from."""
    client = OpenAlexClient()
    candidates = client.search_works(learning_goal, per_page=candidate_pool_size)
    if not candidates:
        return []

    for c in candidates:
        papers_repo.upsert_paper(session, c)

    ids = [c["id"] for c in candidates]
    ranked_ids = semantic.semantic_rank(session, ids, learning_goal)
    by_id = {c["id"]: c for c in candidates}
    stage2_pool = [by_id[i] for i in ranked_ids[:20] if i in by_id]

    listing = "\n".join(
        f'- id={p["id"]} | title="{p["title"]}" | year={p.get("publication_year")} | '
        f'citations={p.get("cited_by_count", 0)} | abstract={(p.get("abstract") or "")[:400]}'
        for p in stage2_pool
    )
    prompt = f"""You are selecting entry-point papers for a first-time learner whose goal is:
"{learning_goal}"

Candidate papers:
{listing}

Task:
1. Exclude any that are tangential to the goal, retracted, non-English, or too narrow/niche for a first-time learner.
2. From what's left, select {max_entry_points} at most as the best entry points — favor review/survey
   papers and highly-cited foundational work over narrow recent applications.

Respond with ONLY a JSON object, no other text:
{{"entry_points": [{{"id": "<paper id>", "reason": "<one short sentence why this is a good entry point>"}}]}}"""

    response = llm.chat([{"role": "user", "content": prompt}])
    parsed = _extract_json(response.choices[0].message.content)

    entry_points = []
    for item in parsed.get("entry_points", [])[:max_entry_points]:
        paper = by_id.get(item.get("id"))
        if paper is None:
            continue
        entry_points.append(
            EntryPointPaper(
                paper_id=paper["id"], title=paper["title"],
                abstract=paper.get("abstract") or "", reason=item.get("reason", ""),
            )
        )
    return entry_points


def score_readability(text: str) -> float:
    """Flesch-Kincaid grade level — lower is simpler. Layer 1 should be ~6th grade or below."""
    return textstat.flesch_kincaid_grade(text)


def check_faithfulness(explanation: str, source_abstract: str) -> tuple[bool, str]:
    """LLM-judge pass: does the simplified explanation claim anything the source
    abstract doesn't support? Returns (is_faithful, reason)."""
    prompt = f"""Source abstract:
{source_abstract}

Simplified explanation:
{explanation}

Does the explanation contain any factual claim that is NOT supported by the source abstract
(including implied certainty the source doesn't actually state)? Respond with ONLY one line:
"FAITHFUL" if every claim is supported, or "UNFAITHFUL: <the specific unsupported claim>" if not."""
    response = llm.chat([{"role": "user", "content": prompt}])
    content = (response.choices[0].message.content or "").strip()
    is_faithful = content.upper().startswith("FAITHFUL")
    return is_faithful, content


def generate_layer_explanation(
    concept_title: str,
    evidence_snippets: list[str],
    layer: int,
    avoid_analogies: list[str] | None = None,
    retry_feedback: str | None = None,
) -> str:
    """Generates one explanation at one layer. `avoid_analogies` — prior explanation
    texts to differ from — is how "explain differently" gets a fresh analogy
    instead of a reworded copy of the last one. `retry_feedback` is the automated
    validation loop's channel (see generate_validated_explanation), separate from
    avoid_analogies since it's about fixing a specific problem, not variety."""
    if layer not in LAYER_RULES:
        raise ValueError(f"layer must be 1, 2, or 3, got {layer}")

    evidence_text = "\n\n".join(evidence_snippets)
    avoid_clause = ""
    if avoid_analogies:
        prior = "\n".join(f"- {a}" for a in avoid_analogies)
        avoid_clause = f"\n\nYou already tried these explanations — use a genuinely different analogy, not a reworded version:\n{prior}"
    feedback_clause = f"\n\nYour previous attempt was rejected: {retry_feedback}\nFix that specific problem." if retry_feedback else ""

    prompt = f"""Explain this concept: "{concept_title}"

Source evidence (ground every claim in this, never go beyond it):
{evidence_text}

Layer rules: {LAYER_RULES[layer]}{avoid_clause}{feedback_clause}

Output ONLY the explanation text — no preamble, no "Here's an explanation:", no markdown headers."""

    response = llm.chat([{"role": "user", "content": prompt}])
    return (response.choices[0].message.content or "").strip()


@dataclass
class ValidatedExplanation:
    content: str
    layer: int
    reading_grade: float
    faithful: bool
    attempts: int
    gave_up: bool  # hit max_attempts without passing every gate that applies to this layer
    history: list[str] = field(default_factory=list)  # rejection reasons, in order


READABILITY_GRADE_CEILING = 6  # spec: reject/regenerate any Layer 1 explanation above this


def generate_validated_explanation(
    concept_title: str, evidence_snippets: list[str], layer: int, max_attempts: int = 3
) -> ValidatedExplanation:
    """Wraps generate_layer_explanation with the eval gates the spec requires
    running from day one: faithfulness is checked at every layer (non-negotiable),
    the Flesch-Kincaid ceiling only applies to Layer 1. Regenerates with specific
    feedback about what failed, not a blind retry."""
    history: list[str] = []
    feedback: str | None = None
    content = ""
    grade = 0.0
    faithful = False

    for attempt in range(1, max_attempts + 1):
        content = generate_layer_explanation(concept_title, evidence_snippets, layer, retry_feedback=feedback)
        grade = score_readability(content)
        faithful, faithfulness_reason = check_faithfulness(content, "\n\n".join(evidence_snippets))

        problems = []
        if layer == 1 and grade > READABILITY_GRADE_CEILING:
            # Flesch-Kincaid penalizes sentence *length* far more than vocabulary —
            # a vocabulary-simple but long-flowing paragraph still scores high, so
            # the feedback has to say "shorter sentences," not just restate the number.
            problems.append(
                f"reading level scored grade {grade:.1f}, needs to be at or below grade "
                f"{READABILITY_GRADE_CEILING} — this is almost always a sentence-length problem, "
                "not a vocabulary problem: use short, simple sentences (roughly 8-12 words each), "
                "one idea per sentence, instead of longer flowing ones"
            )
        if not faithful:
            problems.append(faithfulness_reason)

        if not problems:
            return ValidatedExplanation(content, layer, grade, faithful, attempt, gave_up=False, history=history)

        feedback = "; ".join(problems)
        history.append(feedback)

    return ValidatedExplanation(content, layer, grade, faithful, max_attempts, gave_up=True, history=history)


def generate_comprehension_question(concept_title: str, explanation: str) -> str:
    """A single 'does this make sense' style check — answerable directly from
    the explanation just given, not a jargon-recall quiz."""
    prompt = f"""Explanation given to the learner about "{concept_title}":
{explanation}

Write ONE simple question that checks whether they understood this explanation
(answerable directly from the text above, in their own words — not a jargon-recall quiz).
Output ONLY the question."""
    response = llm.chat([{"role": "user", "content": prompt}])
    return (response.choices[0].message.content or "").strip()
