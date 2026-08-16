"""test_search_works_live hits the real OpenAlex API (no mocking, no credentials
required) — this is the one piece of the stack with no infra dependency, so it's
worth verifying against the real service rather than a fixture."""

import pytest

from research_copilot.openalex_client import OpenAlexClient, normalize_work, reconstruct_abstract


def test_reconstruct_abstract():
    inverted = {"Deep": [0], "learning": [1], "is": [2], "powerful": [3]}
    assert reconstruct_abstract(inverted) == "Deep learning is powerful"


def test_reconstruct_abstract_handles_repeated_words():
    inverted = {"the": [0, 2], "cat": [1], "dog": [3]}
    assert reconstruct_abstract(inverted) == "the cat the dog"


def test_reconstruct_abstract_none_when_missing():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_normalize_work_maps_core_fields():
    raw = {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.1000/xyz",
        "title": "Attention Is All You Need",
        "publication_year": 2017,
        "cited_by_count": 100000,
        "open_access": {"oa_status": "green", "oa_url": "https://example.org/oa"},
        "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"},
        "primary_location": {"source": {"display_name": "NeurIPS"}},
        "abstract_inverted_index": {"We": [0], "propose": [1], "Transformers": [2]},
        "authorships": [
            {
                "author": {"id": "https://openalex.org/A123", "display_name": "A. Vaswani", "orcid": None},
                "author_position": "first",
                "institutions": [{"display_name": "Google Brain"}],
            }
        ],
        "topics": [{"id": "T1", "display_name": "Deep Learning", "score": 0.9}],
        "referenced_works": ["https://openalex.org/W111", "https://openalex.org/W222"],
    }
    normalized = normalize_work(raw)

    assert normalized["id"] == "W2741809807"
    assert normalized["title"] == "Attention Is All You Need"
    assert normalized["abstract"] == "We propose Transformers"
    assert normalized["oa_pdf_url"] == "https://example.org/paper.pdf"
    assert normalized["venue"] == "NeurIPS"
    assert normalized["referenced_works"] == ["W111", "W222"]
    assert normalized["authors"][0]["id"] == "A123"
    assert normalized["authors"][0]["institution_name"] == "Google Brain"


@pytest.mark.integration
def test_search_works_live():
    client = OpenAlexClient()
    results = client.search_works("transformer neural network architecture", per_page=5)

    assert len(results) > 0
    top = results[0]
    assert top["id"].startswith("W")
    assert top["title"]
    assert isinstance(top["cited_by_count"], int)
    # sorted by cited_by_count desc, as requested
    assert results == sorted(results, key=lambda p: p["cited_by_count"], reverse=True)


@pytest.mark.integration
def test_get_work_live():
    # "Attention Is All You Need" — stable, well-known OpenAlex ID
    client = OpenAlexClient()
    work = client.get_work("W2741809807")
    assert work["title"]
    assert work["publication_year"] and work["publication_year"] <= 2018
    assert work["cited_by_count"] > 1000
