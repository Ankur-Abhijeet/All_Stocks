"""
src/mf_faq/ingestion/fetcher.py
=================================
Phase 1.1 — Fetcher (top-level re-export shim)

The implementation lives in:
    src/mf_faq/ingestion/phase_1_1_fetcher/fetcher.py

This shim re-exports the public API so that existing imports of the form:
    from mf_faq.ingestion.fetcher import Fetcher
continue to work without change.
"""

from mf_faq.ingestion.phase_1_1_fetcher.fetcher import (  # noqa: F401
    AllSchemesFetchError,
    ContentTooShortError,
    FetchError,
    FetchResult,
    FetchSummary,
    Fetcher,
    WhitelistViolationError,
    _load_etag_cache,
    _latest_snapshot,
    _parse_retry_after,
    _save_etag_cache,
    _validate_content_length,
    _validate_final_url,
)

__all__ = [
    "Fetcher",
    "FetchResult",
    "FetchSummary",
    "FetchError",
    "AllSchemesFetchError",
    "WhitelistViolationError",
    "ContentTooShortError",
]
