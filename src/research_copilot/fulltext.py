"""Full-text ingestion: downloads a paper's open-access PDF (when OpenAlex has
one), extracts plain text, and caches it as `paper_chunks` rows.

Real limitation, stated plainly rather than glossed over: this only works for
the subset of papers OpenAlex marks open-access with a direct PDF link
(`paper.oa_pdf_url`) — most paywalled papers have none, and this deliberately
doesn't attempt to defeat that. Extraction quality also varies with the PDF's
own layout (multi-column papers, scanned/image-only pages, and running
headers/footers bleeding into the text are all real pypdf limitations, not
bugs here) — this is "real text from the real paper," not a structure-aware
parse like Grobid would give you.
"""

from __future__ import annotations

import io
import logging

import requests
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy.orm import Session

from research_copilot.models import Paper
from research_copilot.repositories import chunks as chunks_repo

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = (10, 30)  # (connect, read) seconds
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # 25MB — guards against a mislinked, huge, or non-PDF response
MAX_STORED_CHARS = 150_000  # generous for any real paper; guards a pathological scanned-book PDF
CHUNK_SIZE = 1500


class FullTextUnavailable(RuntimeError):
    pass


def _download_pdf(url: str) -> bytes:
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT, stream=True, headers={"Accept": "application/pdf"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FullTextUnavailable(f"couldn't fetch the PDF: {exc}") from exc

    chunks: list[bytes] = []
    total = 0
    for piece in resp.iter_content(chunk_size=65536):
        total += len(piece)
        if total > MAX_DOWNLOAD_BYTES:
            raise FullTextUnavailable("PDF exceeds the size limit for full-text ingestion")
        chunks.append(piece)
    data = b"".join(chunks)

    content_type = resp.headers.get("Content-Type", "")
    looks_like_pdf = "pdf" in content_type.lower() or data[:5] == b"%PDF-"
    if not looks_like_pdf:
        raise FullTextUnavailable("the open-access link isn't a direct PDF (likely an HTML landing page)")
    return data


def _extract_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        # pypdf can emit NUL bytes for certain font encodings — Postgres text
        # columns reject those outright (DataError), so strip before storing.
        pages = [(page.extract_text() or "").replace("\x00", "") for page in reader.pages]
    except PdfReadError as exc:
        raise FullTextUnavailable(f"couldn't parse the PDF: {exc}") from exc
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise FullTextUnavailable("no extractable text (likely a scanned, image-only PDF)")
    return text[:MAX_STORED_CHARS]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Paragraph-aware packing: greedily fills each chunk with whole paragraphs
    up to chunk_size, hard-splitting only a single paragraph that's already
    longer than chunk_size on its own."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), chunk_size):
                chunks.append(para[i : i + chunk_size])
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > chunk_size:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def ensure_full_text(session: Session, paper: Paper) -> str | None:
    """Returns the paper's full text, from cache if already ingested, else
    fetches+extracts+caches it now. Returns None if there's no open-access PDF
    to try, or if fetching/extraction fails for any reason — callers fall back
    to the abstract rather than surfacing this as an error, since a missing or
    unparseable PDF is an expected, common case, not a bug."""
    cached = chunks_repo.get_full_text(session, paper.id)
    if cached:
        return cached

    if not paper.oa_pdf_url:
        return None

    try:
        pdf_bytes = _download_pdf(paper.oa_pdf_url)
        text = _extract_text(pdf_bytes)
    except FullTextUnavailable as exc:
        logger.info("Full-text ingestion skipped for %s: %s", paper.id, exc)
        return None

    pieces = chunk_text(text)
    chunks_repo.store_chunks(session, paper.id, pieces)
    return text
