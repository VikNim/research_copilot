"""Thin wrapper over the OpenAlex REST API — called directly, no MCP layer.

Credit-conscious by design: uses filtered list requests (`filter=...`, 10 credits)
for discovery instead of OpenAlex's relevance/text-search endpoints (1,000 credits),
since retrieval quality comes from our own embeddings (see embeddings.py), not theirs.
Every result is meant to be cached into `papers`/`authors` — see repositories/papers.py —
so the same work is never re-fetched.

No credentials required for casual use as of OpenAlex's current docs; an API key
(OPENALEX_API_KEY) raises your daily credit allowance if you have one.
"""

from __future__ import annotations

import logging

import requests

from research_copilot.config import Settings, get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org"
DEFAULT_TIMEOUT = 15


class OpenAlexError(RuntimeError):
    pass


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]} rather than plain text
    (a copyright-driven design choice on their end) — rebuild it here."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


class OpenAlexClient:
    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None):
        self.settings = settings or get_settings()
        self.session = session or requests.Session()

    def _params(self, extra: dict) -> dict:
        params = dict(extra)
        if self.settings.openalex_api_key:
            params["api_key"] = self.settings.openalex_api_key
        elif self.settings.openalex_mailto:
            params["mailto"] = self.settings.openalex_mailto
        return params

    def _get(self, path: str, params: dict) -> dict:
        url = f"{BASE_URL}{path}"
        try:
            resp = self.session.get(url, params=self._params(params), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise OpenAlexError(f"OpenAlex request failed: {exc}") from exc
        return resp.json()

    def search_works(
        self,
        query: str,
        per_page: int = 10,
        filters: dict[str, str] | None = None,
        sort: str | None = None,
    ) -> list[dict]:
        """Filtered list request: title/abstract match plus any extra filters
        (e.g. `publication_year`, `topics.id`). 10 credits, not 1,000.

        No `sort` by default — OpenAlex's own relevance ranking runs, which is
        what actually determines which papers make it into the candidate pool
        at all. An earlier version hardcoded `cited_by_count:desc` here, which
        doesn't re-order an already-relevant set (that's what the UI's "sort
        by citations" option is for) — it *replaces* relevance ranking with raw
        citation count before anything downstream ever sees the results,
        silently dropping genuinely on-topic papers in favor of unrelated
        highly-cited ones that merely mention the query term once. Confirmed
        live: searching "caching" returned XGBoost and GANs ahead of actual
        caching papers with the forced sort; removing it made all 15 results
        genuinely about caching. Only pass `sort` explicitly if a caller has a
        real reason to want OpenAlex's server-side ordering instead of relevance."""
        filter_clauses = [f"title_and_abstract.search:{query}"]
        for key, value in (filters or {}).items():
            filter_clauses.append(f"{key}:{value}")

        params = {"filter": ",".join(filter_clauses), "per_page": per_page}
        if sort:
            params["sort"] = sort

        data = self._get("/works", params)
        return [normalize_work(w) for w in data.get("results", [])]

    def get_work(self, openalex_id: str) -> dict:
        """Singleton lookup — 1 credit."""
        data = self._get(f"/works/{openalex_id}", {})
        return normalize_work(data)


def normalize_work(raw: dict) -> dict:
    """Maps an OpenAlex `works` record onto our `papers` + `authors` schema shape."""
    open_access = raw.get("open_access") or {}
    best_oa = raw.get("best_oa_location") or {}
    primary_location = raw.get("primary_location") or {}
    source = primary_location.get("source") or {}

    authors = []
    for authorship in raw.get("authorships", []):
        author = authorship.get("author") or {}
        institutions = authorship.get("institutions") or []
        if not author.get("id"):
            continue
        authors.append(
            {
                "id": author["id"].rsplit("/", 1)[-1],
                "display_name": author.get("display_name"),
                "orcid": author.get("orcid"),
                "institution_name": institutions[0]["display_name"] if institutions else None,
                "author_position": authorship.get("author_position"),
            }
        )

    topics = [
        {"id": t.get("id"), "display_name": t.get("display_name"), "score": t.get("score")}
        for t in raw.get("topics", [])
    ]

    return {
        "id": raw.get("id", "").rsplit("/", 1)[-1] if raw.get("id") else None,
        "doi": raw.get("doi"),
        "title": raw.get("title") or raw.get("display_name") or "(untitled)",
        "abstract": reconstruct_abstract(raw.get("abstract_inverted_index")),
        "publication_year": raw.get("publication_year"),
        "venue": source.get("display_name"),
        "oa_status": open_access.get("oa_status"),
        "oa_pdf_url": best_oa.get("pdf_url") or open_access.get("oa_url"),
        "cited_by_count": raw.get("cited_by_count", 0),
        "topics": topics,
        "referenced_works": [rw.rsplit("/", 1)[-1] for rw in raw.get("referenced_works", [])],
        "authors": authors,
        "openalex_raw": raw,
    }
