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


# OpenAlex's cheap filter search (title_and_abstract.search:<query>) matches
# with an implicit AND across every word in <query> — fine for a short phrase,
# but this app's own landing page asks for a full topic in plain language
# ("point of sale systems from a data engineering perspective"), and it's
# common for no single paper's title+abstract to contain literally every word
# of an 8-word sentence. Confirmed live: dropping connective words like "of"/
# "from"/"perspective" turns a real 0-result search into 5 results for the
# exact same underlying topic. These are stripped before the AND retry below.
_STOPWORDS = {
    "a", "an", "the", "of", "from", "in", "on", "at", "for", "with", "about",
    "into", "to", "and", "or", "is", "are", "was", "were", "be", "as", "by",
    "how", "what", "why", "does", "do", "this", "that",
}


def _significant_words(query: str) -> list[str]:
    return [w for w in query.split() if w.lower().strip("()[]{}.,;:!?") not in _STOPWORDS]


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
        real reason to want OpenAlex's server-side ordering instead of relevance.

        A natural-language query that matches nothing is retried before giving
        up — see _STOPWORDS above for why this is needed at all:
        1. Drop connective words, keep AND semantics (still the cheap 10-credit
           filter endpoint) — catches cases where one word like "from" broke
           an otherwise-matchable AND.
        2. If that's still nothing, fall back once to OpenAlex's real
           relevance-ranked full-text search (`search=`, ~1,000 credits).
           Tried OR-of-words on the cheap endpoint here first — it technically
           returns *something*, but confirmed live it's the same failure mode
           as the citation-bias bug this file already fixed once: generic
           words like "data" or "point" OR-matched into millions of unrelated
           papers, with hyper-cited noise (RNA-seq pipelines, PCR protocols)
           crowding out anything actually relevant. A blank screen is bad; a
           screen full of confidently-wrong papers is worse. This fallback
           only fires when the cheap path found literally nothing, so it's
           the rare case, not every search."""
        extra_filters = [f"{key}:{value}" for key, value in (filters or {}).items()]

        def _run_filter(search_term: str) -> list[dict]:
            filter_clauses = [f"title_and_abstract.search:{search_term}", *extra_filters]
            params = {"filter": ",".join(filter_clauses), "per_page": per_page}
            if sort:
                params["sort"] = sort
            data = self._get("/works", params)
            return [normalize_work(w) for w in data.get("results", [])]

        results = _run_filter(query)
        if results:
            return results

        words = _significant_words(query)
        if len(words) >= 2 and len(words) < len(query.split()):
            results = _run_filter(" ".join(words))
            if results:
                return results

        fallback_params = {"search": query, "per_page": per_page}
        if extra_filters:
            fallback_params["filter"] = ",".join(extra_filters)
        data = self._get("/works", fallback_params)
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
