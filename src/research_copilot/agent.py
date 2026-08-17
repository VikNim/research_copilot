"""The copilot agent: one Claude model (via llm.py), six tools, mapped straight
to the capabilities in the blueprint. UNVERIFIED end-to-end — needs a real
Databricks FM API endpoint (see llm.py). The tool-dispatch plumbing and each
tool's DB-side logic are real and independently testable through the
repositories/sequencing modules they call.

v1 note: retrieve_evidence works at abstract granularity (no paper_chunks yet —
full-text ingestion is deferred). Still "retrieve, don't dump": the agent passes
a specific paper_id subset, not the user's whole library.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from research_copilot import llm
from research_copilot.openalex_client import OpenAlexClient
from research_copilot.repositories import collections as collections_repo
from research_copilot.repositories import goals as goals_repo
from research_copilot.repositories import papers as papers_repo
from research_copilot.repositories import progress as progress_repo
from research_copilot.sequencing import sequence_reading_plan

SYSTEM_PROMPT = """You are a research and learning copilot. You help users turn a
learning goal into a sequenced, evidence-grounded reading plan.

Rules:
- Every factual claim about a paper must cite it inline as (Author, Year) with its
  OpenAlex ID, using only papers returned by your tools — never invent a citation.
- Use retrieve_evidence for summarizing or comparing papers rather than relying on
  what you already know about them; ground every answer in what the tool returns.
- If the user refers to "these papers" / "this collection" without naming specific
  papers, call list_collection_papers first (using the active collection_id, if
  you've been given one) rather than asking them to re-list what's already saved.
- Prefer the fewest tool calls that answer the question well.
"""

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": "Find papers on OpenAlex matching a topic and cache them locally.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to search for"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_collection_papers",
            "description": "List the papers already saved in a collection (id, title, year, citations) — use this to find out what's in a collection before comparing or summarizing 'these papers'.",
            "parameters": {
                "type": "object",
                "properties": {"collection_id": {"type": "string"}},
                "required": ["collection_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_evidence",
            "description": "Get grounded evidence (abstract + metadata + citation) for a specific set of papers, to summarize or compare.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["paper_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_reading_plan",
            "description": "Sequence a collection's papers into Review -> Foundational -> Current reading order and save it.",
            "parameters": {
                "type": "object",
                "properties": {"collection_id": {"type": "string"}},
                "required": ["collection_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_collection",
            "description": "Add a paper to a collection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string"},
                    "paper_id": {"type": "string"},
                },
                "required": ["collection_id", "paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_next",
            "description": "Recommend the next unread paper in a collection, following its reading order.",
            "parameters": {
                "type": "object",
                "properties": {"collection_id": {"type": "string"}},
                "required": ["collection_id"],
            },
        },
    },
]


def _tool_search_papers(session: Session, args: dict) -> dict:
    client = OpenAlexClient()
    results = client.search_works(args["query"], per_page=args.get("limit", 10))
    saved = [papers_repo.upsert_paper(session, r) for r in results]
    return {
        "papers": [
            {"id": p.id, "title": p.title, "year": p.publication_year, "cited_by_count": p.cited_by_count}
            for p in saved
        ]
    }


def _tool_list_collection_papers(session: Session, args: dict) -> dict:
    papers = collections_repo.list_papers_in_collection(session, uuid.UUID(args["collection_id"]))
    return {
        "papers": [
            {"id": p.id, "title": p.title, "year": p.publication_year, "cited_by_count": p.cited_by_count}
            for p in papers
        ]
    }


def _tool_retrieve_evidence(session: Session, args: dict) -> dict:
    papers = papers_repo.list_papers_by_ids(session, args["paper_ids"])
    evidence = []
    for p in papers:
        authors = ", ".join(link.author.display_name for link in p.authors if link.author.display_name)
        evidence.append(
            {
                "paper_id": p.id,
                "citation": f"({authors or 'Unknown'}, {p.publication_year})",
                "title": p.title,
                "abstract": p.abstract,
            }
        )
    return {"evidence": evidence}


def generate_reading_plan_for_collection(session: Session, collection_id: str) -> dict:
    """Public entry point for triggering the sequencer directly from the UI
    (Screen 3's "Generate reading plan" button), without going through the chat loop."""
    return _tool_generate_reading_plan(session, {"collection_id": collection_id})


def _tool_generate_reading_plan(session: Session, args: dict) -> dict:
    collection_id = uuid.UUID(args["collection_id"])
    papers = collections_repo.list_papers_in_collection(session, collection_id)
    paper_dicts = [
        {
            "id": p.id,
            "cited_by_count": p.cited_by_count,
            "publication_year": p.publication_year,
            "referenced_works": (p.openalex_raw or {}).get("referenced_works", []),
        }
        for p in papers
    ]
    # openalex_raw stores full "https://openalex.org/W..." URLs for referenced_works;
    # normalize to bare IDs to match how paper.id is stored, so in-set matching works.
    for pd in paper_dicts:
        pd["referenced_works"] = [rw.rsplit("/", 1)[-1] for rw in pd["referenced_works"]]

    plan = sequence_reading_plan(paper_dicts)
    collections_repo.set_positions(session, collection_id, [s.paper_id for s in plan])
    return {
        "plan": [
            {"paper_id": s.paper_id, "position": s.position, "stage": s.stage, "rationale": s.rationale}
            for s in plan
        ]
    }


def _tool_add_to_collection(session: Session, args: dict) -> dict:
    link = collections_repo.add_paper(
        session, collection_id=uuid.UUID(args["collection_id"]), paper_id=args["paper_id"]
    )
    return {"collection_id": str(link.collection_id), "paper_id": link.paper_id, "position": link.position}


def _tool_recommend_next(session: Session, args: dict, user_id: uuid.UUID) -> dict:
    collection_id = uuid.UUID(args["collection_id"])
    ordered = [p.id for p in collections_repo.list_papers_in_collection(session, collection_id)]
    next_id = progress_repo.recommend_next(session, user_id=user_id, collection_id=collection_id, ordered_paper_ids=ordered)
    return {"next_paper_id": next_id}


def _dispatch(session: Session, user_id: uuid.UUID, name: str, args: dict) -> dict:
    if name == "search_papers":
        return _tool_search_papers(session, args)
    if name == "list_collection_papers":
        return _tool_list_collection_papers(session, args)
    if name == "retrieve_evidence":
        return _tool_retrieve_evidence(session, args)
    if name == "generate_reading_plan":
        return _tool_generate_reading_plan(session, args)
    if name == "add_to_collection":
        return _tool_add_to_collection(session, args)
    if name == "recommend_next":
        return _tool_recommend_next(session, args, user_id)
    raise ValueError(f"Unknown tool: {name}")


def run_agent(
    session: Session,
    user_id: uuid.UUID,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    max_tool_rounds: int = 4,
    context_note: str | None = None,
) -> list[dict[str, Any]]:
    """Runs the tool-use loop; returns the updated message history (append-only,
    so callers can persist/display it as a chat transcript).

    `context_note` — e.g. "the active collection_id is <uuid>" — is folded into
    the system prompt for this call only, not the visible user message, so a
    chat UI can tell the agent which collection is in scope without an injected
    context line showing up in what the user actually typed.
    """
    system_content = SYSTEM_PROMPT if not context_note else f"{SYSTEM_PROMPT}\n\n{context_note}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    for _ in range(max_tool_rounds):
        response = llm.chat(messages, tools=TOOL_SCHEMAS)
        choice = response.choices[0].message
        messages.append(choice.model_dump(exclude_none=True))

        if not choice.tool_calls:
            break

        for call in choice.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            try:
                result = _dispatch(session, user_id, call.function.name, args)
            except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
                result = {"error": str(exc)}
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )

    return messages[1:]  # drop the system prompt from what callers display/persist
