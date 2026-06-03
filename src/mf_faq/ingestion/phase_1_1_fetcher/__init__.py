"""
mf_faq.ingestion.phase_1_1_fetcher
=====================================
Phase 1.1 — Fetcher sub-package

Public API re-exported for convenience:

    from mf_faq.ingestion.phase_1_1_fetcher import Fetcher, FetchResult, FetchSummary
"""

from mf_faq.ingestion.phase_1_1_fetcher.fetcher import (
    AllSchemesFetchError,
    ContentTooShortError,
    FetchError,
    FetchResult,
    FetchSummary,
    Fetcher,
    WhitelistViolationError,
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
