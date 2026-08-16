"""Papers/authors are a pull-through cache of OpenAlex — upsert_paper is the only
write path, called after every openalex_client fetch so the same work is never
re-fetched (see openalex_client.py's module docstring)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from research_copilot.models import Author, Paper, PaperAuthor


def upsert_paper(session: Session, normalized: dict) -> Paper:
    paper = session.get(Paper, normalized["id"])
    if paper is None:
        paper = Paper(id=normalized["id"])
        session.add(paper)

    paper.doi = normalized.get("doi")
    paper.title = normalized["title"]
    paper.abstract = normalized.get("abstract")
    paper.publication_year = normalized.get("publication_year")
    paper.venue = normalized.get("venue")
    paper.oa_status = normalized.get("oa_status")
    paper.oa_pdf_url = normalized.get("oa_pdf_url")
    paper.cited_by_count = normalized.get("cited_by_count", 0)
    paper.topics = normalized.get("topics")
    paper.openalex_raw = normalized.get("openalex_raw")
    session.flush()

    for a in normalized.get("authors", []):
        author = session.get(Author, a["id"])
        if author is None:
            author = Author(id=a["id"])
            session.add(author)
        author.display_name = a.get("display_name") or author.display_name or "(unknown)"
        author.orcid = a.get("orcid")
        author.institution_name = a.get("institution_name")
        session.flush()

        link = session.get(PaperAuthor, {"paper_id": paper.id, "author_id": author.id})
        if link is None:
            link = PaperAuthor(paper_id=paper.id, author_id=author.id)
            session.add(link)
        link.author_position = a.get("author_position")

    session.flush()
    return paper


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
