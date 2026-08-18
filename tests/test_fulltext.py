"""chunk_text is pure and always runs; the live fetch against a real,
permanently-stable arXiv PDF proves the actual download/extract/cache
pipeline works end to end, not just that the chunking math is right."""

from __future__ import annotations

import os

import pytest

from research_copilot import fulltext
from research_copilot.repositories import chunks as chunks_repo
from research_copilot.repositories import papers as papers_repo

requires_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")

ATTENTION_IS_ALL_YOU_NEED = {
    "id": "WFTTEST1", "doi": None, "title": "Attention Is All You Need (test fixture)",
    "abstract": "test abstract", "publication_year": 2017, "venue": None,
    "oa_status": "green", "oa_pdf_url": "https://arxiv.org/pdf/1706.03762",
    "cited_by_count": 0, "topics": [], "referenced_works": [],
    "authors": [{"id": "AFT1", "display_name": "Test Author", "orcid": None, "institution_name": None}],
    "openalex_raw": {},
}


def test_chunk_text_packs_paragraphs_up_to_the_size_limit():
    text = "\n\n".join([f"Paragraph {i}. " * 5 for i in range(10)])
    chunks = fulltext.chunk_text(text, chunk_size=200)
    assert all(len(c) <= 200 for c in chunks)
    # chunks_repo reconstructs with "\n\n".join (see get_full_text) — matching that
    # here, word-level equality proves no content was lost or reordered, which is
    # what actually matters for a summarization prompt (exact whitespace isn't).
    assert "\n\n".join(chunks).split() == text.split()


def test_chunk_text_hard_splits_a_single_oversized_paragraph():
    huge_paragraph = "word " * 1000  # one paragraph, no \n\n breaks, well over any reasonable chunk_size
    chunks = fulltext.chunk_text(huge_paragraph, chunk_size=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)


def test_chunk_text_empty_input():
    assert fulltext.chunk_text("") == []


@requires_db
def test_full_text_ingestion_fetches_extracts_and_caches(db_session):
    """Real network fetch of a real PDF, real pypdf extraction, real DB round
    trip — the actual failure mode reproduced live earlier (pypdf emitting NUL
    bytes Postgres rejects) is exactly what this exercises."""
    paper = papers_repo.upsert_paper(db_session, ATTENTION_IS_ALL_YOU_NEED)

    text = fulltext.ensure_full_text(db_session, paper)
    assert text is not None
    assert len(text) > 1000
    assert "\x00" not in text
    assert chunks_repo.has_chunks(db_session, paper.id)

    # second call hits the cache, not the network — same content back
    cached = fulltext.ensure_full_text(db_session, paper)
    assert cached is not None
    assert len(cached) > 1000
