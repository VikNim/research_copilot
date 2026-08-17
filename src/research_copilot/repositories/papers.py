"""Papers/authors are a pull-through cache of OpenAlex — upsert_paper is the only
write path, called after every openalex_client fetch so the same work is never
re-fetched (see openalex_client.py's module docstring).

Every write here uses `INSERT ... ON CONFLICT DO UPDATE` rather than a
check-then-insert (session.get() -> if None: add()) pattern deliberately: papers
and authors are a *shared* cache across every user, so two different people
searching overlapping topics at the same time will race to insert the same
OpenAlex id. Proven for real under concurrent load (20 simulated simultaneous
users caching the same paper) — check-then-insert threw a UniqueViolation on
the second writer; the atomic upsert below doesn't."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from research_copilot.models import Author, Paper, PaperAuthor


def upsert_paper(session: Session, normalized: dict) -> Paper:
    # embedding is deliberately excluded from the update SET — it's written
    # separately (see semantic.py) and must survive a paper being re-upserted
    # by a later search that doesn't carry a vector with it.
    stmt = pg_insert(Paper).values(
        id=normalized["id"],
        doi=normalized.get("doi"),
        title=normalized["title"],
        abstract=normalized.get("abstract"),
        publication_year=normalized.get("publication_year"),
        venue=normalized.get("venue"),
        oa_status=normalized.get("oa_status"),
        oa_pdf_url=normalized.get("oa_pdf_url"),
        cited_by_count=normalized.get("cited_by_count", 0),
        topics=normalized.get("topics"),
        openalex_raw=normalized.get("openalex_raw"),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Paper.id],
        set_={
            "doi": stmt.excluded.doi,
            "title": stmt.excluded.title,
            "abstract": stmt.excluded.abstract,
            "publication_year": stmt.excluded.publication_year,
            "venue": stmt.excluded.venue,
            "oa_status": stmt.excluded.oa_status,
            "oa_pdf_url": stmt.excluded.oa_pdf_url,
            "cited_by_count": stmt.excluded.cited_by_count,
            "topics": stmt.excluded.topics,
            "openalex_raw": stmt.excluded.openalex_raw,
        },
    )
    session.execute(stmt)

    for a in normalized.get("authors", []):
        author_stmt = pg_insert(Author).values(
            id=a["id"],
            display_name=a.get("display_name") or "(unknown)",
            orcid=a.get("orcid"),
            institution_name=a.get("institution_name"),
        )
        author_stmt = author_stmt.on_conflict_do_update(
            index_elements=[Author.id],
            set_={
                "display_name": author_stmt.excluded.display_name,
                "orcid": author_stmt.excluded.orcid,
                "institution_name": author_stmt.excluded.institution_name,
            },
        )
        session.execute(author_stmt)

        link_stmt = pg_insert(PaperAuthor).values(
            paper_id=normalized["id"], author_id=a["id"], author_position=a.get("author_position"),
        )
        link_stmt = link_stmt.on_conflict_do_update(
            index_elements=[PaperAuthor.paper_id, PaperAuthor.author_id],
            set_={"author_position": link_stmt.excluded.author_position},
        )
        session.execute(link_stmt)

    session.flush()
    # populate_existing: see users_repo.upsert_user for why this matters — without
    # it, re-upserting a paper already loaded in this session (e.g. re-fetched by
    # a later search) would return stale pre-update data from the identity map.
    return session.get(Paper, normalized["id"], populate_existing=True)


def get_paper(session: Session, paper_id: str) -> Paper | None:
    return session.get(Paper, paper_id)


def list_papers_by_ids(session: Session, paper_ids: list[str]) -> list[Paper]:
    if not paper_ids:
        return []
    stmt = select(Paper).where(Paper.id.in_(paper_ids))
    by_id = {p.id: p for p in session.scalars(stmt)}
    return [by_id[pid] for pid in paper_ids if pid in by_id]


def semantic_search(session: Session, query_embedding: list[float], limit: int = 10) -> list[Paper]:
    """Cosine-nearest papers to a query vector — used to rank OpenAlex candidates
    or to find papers already in our cache related to a goal/note."""
    stmt = (
        select(Paper)
        .where(Paper.embedding.is_not(None))
        .order_by(Paper.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(session.scalars(stmt))


def rank_by_similarity(session: Session, paper_ids: list[str], query_embedding: list[float]) -> list[Paper]:
    """Same idea as semantic_search, but scoped to a specific candidate set — e.g.
    re-ranking one search's OpenAlex results by meaning rather than the whole cache."""
    if not paper_ids:
        return []
    stmt = (
        select(Paper)
        .where(Paper.id.in_(paper_ids), Paper.embedding.is_not(None))
        .order_by(Paper.embedding.cosine_distance(query_embedding))
    )
    return list(session.scalars(stmt))


def papers_missing_embeddings(session: Session, paper_ids: list[str]) -> list[Paper]:
    if not paper_ids:
        return []
    stmt = select(Paper).where(Paper.id.in_(paper_ids), Paper.embedding.is_(None), Paper.abstract.is_not(None))
    return list(session.scalars(stmt))
