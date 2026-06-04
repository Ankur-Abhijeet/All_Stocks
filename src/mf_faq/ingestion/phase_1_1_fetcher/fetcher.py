"""
src/mf_faq/ingestion/fetcher.py
================================
Phase 1.1 — Fetcher

Responsibility: Download the 5 Groww HTML pages from config/sources.yaml and
persist raw HTML snapshots to data/raw/ with ETag-based change detection.

Design principles:
  - All-or-nothing: a partial fetch (any scheme fails all retries) aborts the
    run without touching data/index/live/. The caller (refresh.py) decides
    whether to proceed or serve the stale index.
  - ETag tracking: only re-persists snapshots when content actually changed.
  - Whitelist enforcement: validates the final response URL (after redirects)
    against sources.yaml — EC-P1F-004.
  - Minimum content guard: rejects HTTP-200 pages with tiny bodies (JS-only
    SPAs / maintenance placeholders) — EC-P1F-006.
  - Stale-snapshot fallback: if a scheme fails all retries but has a previous
    snapshot on disk, the FetchResult carries the stale HTML and changed=False
    so downstream stages can reuse it — EC-P1F-001, EC-P1F-005.

Edge cases handled:
  EC-P1F-001  HTTP 403 Forbidden         → retries with backoff; falls back to stale snapshot
  EC-P1F-002  HTTP 429 Rate-Limit        → respects Retry-After header; falls back to stale
  EC-P1F-003  Corrupted ETag cache       → re-fetches all pages; overwrites cache
  EC-P1F-004  Redirect to non-whitelist  → WhitelistViolation raised; treated as fetch failure
  EC-P1F-005  Timeout on one page        → partial failure sets FetchResult.ok=False; caller
                                            sees overall success=False and aborts index swap
  EC-P1F-006  Empty / placeholder HTML   → ContentTooShortError raised; treated as fetch failure

Output files written:
  data/raw/<scheme_id>_<YYYY-MM-DD>.html  — raw HTML snapshot (only on change)
  data/raw/etag_cache.json                — {scheme_id: etag} mapping
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from requests import Response, Session
from requests.exceptions import ConnectionError, ReadTimeout, Timeout

from mf_faq.config.loader import SchemeConfig, SourcesConfig, load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (defaults — overridden by thresholds.yaml at runtime)
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 30          # seconds
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 2  # seconds (exponential: 2, 4, 8)
_DEFAULT_MIN_CONTENT_BYTES = 5000
_DEFAULT_KEEP_LAST = 3

_ALLOWED_DOMAIN = "https://groww.in/mutual-funds/"

# Browser-like headers to reduce the chance of bot-detection (403)
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FetchError(Exception):
    """Base exception for any unrecoverable fetch error for a single scheme."""


class WhitelistViolationError(FetchError):
    """
    EC-P1F-004: The server redirected to a URL outside the whitelisted domain.
    Hard failure — do not retry.
    """


class ContentTooShortError(FetchError):
    """
    EC-P1F-006: HTTP 200 received but body is too small to be a valid scheme page
    (likely a JS-only SPA or maintenance placeholder).
    """


class AllSchemesFetchError(Exception):
    """
    Raised when every scheme in the corpus fails to fetch and has no stale fallback.
    The caller must abort the ingestion run.
    """


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """
    Result for a single scheme page fetch.

    Attributes:
        scheme_id    : Scheme identifier from sources.yaml (e.g. 'hdfc_mid_cap')
        scheme_name  : Human-readable scheme name
        source_url   : Canonical whitelisted URL from sources.yaml
        html         : Raw HTML string (current or stale)
        etag         : ETag value from the HTTP response, or None
        fetched_at   : ISO date string of when the fetch was attempted
        changed      : True if content changed since last run (new ETag or no cache hit)
        ok           : True if fetch succeeded (fresh or stale fallback available)
                       False if fetch failed and no stale fallback exists
        error        : Human-readable error description when ok=False
        snapshot_path: Path to the persisted HTML file (None if fetch failed entirely)
        is_stale     : True when html came from a previous snapshot (not a fresh fetch)
    """

    scheme_id: str
    scheme_name: str
    source_url: str
    html: str = ""
    etag: Optional[str] = None
    fetched_at: str = ""
    changed: bool = False
    ok: bool = True
    error: str = ""
    snapshot_path: Optional[Path] = None
    is_stale: bool = False


@dataclass
class FetchSummary:
    """
    Aggregate result of fetch_all().

    Attributes:
        results        : Per-scheme FetchResult list (always length 5 on return)
        all_ok         : True only if every scheme has ok=True
        failed_schemes : scheme_ids where ok=False (no fresh or stale data)
        changed_count  : Number of schemes where content actually changed
    """

    results: List[FetchResult]
    all_ok: bool
    failed_schemes: List[str]
    changed_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_project_root() -> Path:
    """Find the project root (the directory that contains config/ and data/)."""
    # src/mf_faq/ingestion/phase_1_1_fetcher/fetcher.py → parents[4] = project root
    return Path(__file__).resolve().parents[4]


def _etag_cache_path(raw_dir: Path) -> Path:
    return raw_dir / "etag_cache.json"


def _load_etag_cache(raw_dir: Path) -> Dict[str, str]:
    """
    EC-P1F-003: Load ETag cache, returning empty dict on corruption or absence.
    A corrupted cache triggers a full re-fetch of all pages.
    """
    cache_path = _etag_cache_path(raw_dir)
    if not cache_path.exists():
        logger.debug("ETag cache not found — treating all pages as changed (bootstrap run).")
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("ETag cache is not a JSON object.")
        logger.debug("ETag cache loaded: %d entries.", len(data))
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "ETag cache at %s is corrupted (%s). Treating all pages as changed.",
            cache_path, exc,
        )
        return {}


def _save_etag_cache(raw_dir: Path, cache: Dict[str, str]) -> None:
    """Persist the updated ETag cache atomically (write to temp then rename)."""
    cache_path = _etag_cache_path(raw_dir)
    tmp_path = cache_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2)
    tmp_path.replace(cache_path)
    logger.debug("ETag cache saved (%d entries).", len(cache))


def _snapshot_path(raw_dir: Path, scheme_id: str, fetch_date: str) -> Path:
    """Return the path for a dated HTML snapshot file."""
    return raw_dir / f"{scheme_id}_{fetch_date}.html"


def _latest_snapshot(raw_dir: Path, scheme_id: str) -> Optional[Path]:
    """
    Return the most recent existing snapshot for scheme_id, or None.
    Used as stale fallback when a live fetch fails.
    """
    candidates = sorted(raw_dir.glob(f"{scheme_id}_*.html"), reverse=True)
    return candidates[0] if candidates else None


def _cleanup_old_snapshots(raw_dir: Path, scheme_id: str, keep_last: int) -> None:
    """
    EC-P1R-002: Retain only the <keep_last> most recent snapshots per scheme
    to prevent disk exhaustion on GitHub Actions runners.
    """
    snapshots = sorted(raw_dir.glob(f"{scheme_id}_*.html"), reverse=True)
    for old in snapshots[keep_last:]:
        try:
            old.unlink()
            logger.debug("Deleted old snapshot: %s", old.name)
        except OSError as exc:
            logger.warning("Could not delete old snapshot %s: %s", old, exc)


def _validate_final_url(final_url: str, allowed_domain: str, scheme_id: str) -> None:
    """
    EC-P1F-004: After redirects, assert the response URL is still on the
    whitelisted domain. Raises WhitelistViolationError on mismatch.
    """
    if not final_url.startswith(allowed_domain):
        raise WhitelistViolationError(
            f"[{scheme_id}] Server redirected to a non-whitelisted URL: '{final_url}'. "
            f"Expected domain: '{allowed_domain}'. Aborting fetch for this scheme."
        )


def _validate_content_length(html: str, min_bytes: int, scheme_id: str) -> None:
    """
    EC-P1F-006: Guard against HTTP-200 responses with too-small bodies
    (maintenance placeholders, JS-only SPAs without SSR).
    """
    actual_bytes = len(html.encode("utf-8"))
    if actual_bytes < min_bytes:
        raise ContentTooShortError(
            f"[{scheme_id}] Response body is only {actual_bytes} bytes "
            f"(minimum: {min_bytes}). Likely a placeholder or empty page."
        )


def _parse_retry_after(response: Response) -> float:
    """Parse Retry-After header (seconds or HTTP date). Returns wait_seconds."""
    header = response.headers.get("Retry-After", "")
    if header.isdigit():
        return float(header)
    # HTTP-date format — default to 60s if unparseable
    return 60.0


def _fetch_with_retry(
    session: Session,
    scheme: SchemeConfig,
    etag_cache: Dict[str, str],
    timeout: int,
    max_retries: int,
    base_delay: float,
    min_content_bytes: int,
    allowed_domain: str,
) -> tuple[str, str | None, bool]:
    """
    Attempt to fetch a single Groww scheme page with exponential backoff.

    Returns:
        (html, etag, changed)

    Raises:
        FetchError (or subclass) if all retries are exhausted.
    """
    scheme_id = scheme.id
    url = scheme.url
    cached_etag = etag_cache.get(scheme_id)

    headers = dict(_REQUEST_HEADERS)
    if cached_etag:
        headers["If-None-Match"] = cached_etag

    last_exc: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "[%s] Fetch attempt %d/%d → %s",
                scheme_id, attempt, max_retries, url,
            )
            resp: Response = session.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

            # EC-P1F-004: Validate final URL after any redirects
            _validate_final_url(str(resp.url), allowed_domain, scheme_id)

            if resp.status_code == 304:
                # Content not modified — ETag hit
                logger.info("[%s] 304 Not Modified (ETag hit). Content unchanged.", scheme_id)
                return "", cached_etag, False  # caller loads stale snapshot from disk

            if resp.status_code == 200:
                html = resp.text
                _validate_content_length(html, min_content_bytes, scheme_id)
                new_etag = resp.headers.get("ETag")
                changed = (new_etag != cached_etag) if new_etag else True
                logger.info(
                    "[%s] 200 OK — %d bytes, changed=%s, ETag=%s",
                    scheme_id, len(html.encode("utf-8")), changed, new_etag,
                )
                return html, new_etag, changed

            # EC-P1F-002: 429 Rate-Limit — respect Retry-After
            if resp.status_code == 429:
                wait = _parse_retry_after(resp)
                logger.warning(
                    "[%s] HTTP 429 Rate-Limited. Waiting %.0fs before retry %d/%d.",
                    scheme_id, wait, attempt, max_retries,
                )
                time.sleep(wait)
                last_exc = FetchError(f"HTTP 429 after Retry-After wait on attempt {attempt}")
                continue

            # EC-P1F-001: 403 Forbidden or other 4xx/5xx
            if resp.status_code in (403, 503):
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[%s] HTTP %d. Backoff %.1fs before retry %d/%d.",
                    scheme_id, resp.status_code, delay, attempt, max_retries,
                )
                time.sleep(delay)
                last_exc = FetchError(f"HTTP {resp.status_code} on attempt {attempt}")
                continue

            # Any other non-200 status
            raise FetchError(
                f"[{scheme_id}] Unexpected HTTP {resp.status_code} from '{url}'."
            )

        except WhitelistViolationError:
            # Hard failure — do not retry
            raise

        except ContentTooShortError:
            # Hard failure — do not retry (page is genuinely broken)
            raise

        except (Timeout, ReadTimeout, ConnectionError) as exc:
            # EC-P1F-005: Network timeout / connection error
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "[%s] Network error on attempt %d/%d: %s. Backing off %.1fs.",
                scheme_id, attempt, max_retries, exc, delay,
            )
            last_exc = FetchError(f"Network error: {exc}")
            if attempt < max_retries:
                time.sleep(delay)

    # All retries exhausted
    raise FetchError(
        f"[{scheme_id}] All {max_retries} fetch attempts failed. "
        f"Last error: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class Fetcher:
    """
    Phase 1.1 — Downloads the 5 Groww scheme pages and persists raw HTML
    snapshots in data/raw/.

    Args:
        config_dir : Path to the config/ directory. Defaults to project root / config.
        data_dir   : Path to the data/ directory. Defaults to project root / data.

    Usage:
        fetcher = Fetcher()
        summary = fetcher.fetch_all()
        if not summary.all_ok:
            logger.error("Some schemes failed: %s", summary.failed_schemes)
            # Caller should abort index swap and keep stale index
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        project_root = _resolve_project_root()
        self._config_dir = Path(config_dir) if config_dir else project_root / "config"
        self._raw_dir = (Path(data_dir) if data_dir else project_root / "data") / "raw"
        self._raw_dir.mkdir(parents=True, exist_ok=True)

        # Load and validate Phase 0 config
        self._app_cfg = load_config(config_dir=self._config_dir)
        self._sources: SourcesConfig = self._app_cfg.sources
        thr = self._app_cfg.thresholds

        # Fetch parameters from thresholds.yaml
        self._timeout = thr.request_timeout_seconds
        self._max_retries = thr.max_retries
        self._base_delay = float(thr.retry_base_delay_seconds)
        self._min_content_bytes = thr.min_content_bytes
        self._keep_last = thr.raw_snapshots_keep_last

        logger.info(
            "Fetcher initialised. corpus=%d schemes, timeout=%ds, retries=%d, "
            "min_content=%d bytes.",
            len(self._sources.corpus),
            self._timeout,
            self._max_retries,
            self._min_content_bytes,
        )

    # ------------------------------------------------------------------
    # Public method
    # ------------------------------------------------------------------

    def fetch_all(self) -> FetchSummary:
        """
        Fetch all 5 whitelisted Groww scheme pages.

        For each scheme:
          1. Check ETag cache for a cached ETag.
          2. Issue HTTP GET with If-None-Match; retry up to max_retries on failure.
          3. On 304: content unchanged — load the latest on-disk snapshot as stale.
          4. On 200: persist snapshot; update ETag cache.
          5. On permanent failure: attempt stale fallback from disk.
          6. Clean up old snapshots (keep_last).

        Returns:
            FetchSummary with per-scheme FetchResult objects.
            FetchSummary.all_ok is False when ANY scheme has no data at all
            (no fresh fetch AND no stale fallback). The refresh orchestrator
            must treat all_ok=False as "do not proceed with indexing".

        Raises:
            AllSchemesFetchError: if every single scheme fails and no stale data exists.
        """
        today = str(date.today())
        etag_cache = _load_etag_cache(self._raw_dir)
        updated_etag_cache: Dict[str, str] = dict(etag_cache)

        results: List[FetchResult] = []
        session = self._build_session()

        for scheme in self._sources.corpus:
            result = self._fetch_one(
                session=session,
                scheme=scheme,
                etag_cache=etag_cache,
                updated_etag_cache=updated_etag_cache,
                today=today,
            )
            results.append(result)

        session.close()

        # Persist updated ETag cache regardless of partial failures
        _save_etag_cache(self._raw_dir, updated_etag_cache)

        failed = [r.scheme_id for r in results if not r.ok]
        changed_count = sum(1 for r in results if r.changed)
        all_ok = len(failed) == 0

        if not all_ok:
            logger.error(
                "Fetch completed with %d failure(s): %s. "
                "Caller must NOT proceed with index swap.",
                len(failed), failed,
            )
        else:
            logger.info(
                "Fetch completed. %d/%d changed, %d/%d stale.",
                changed_count,
                len(results),
                sum(1 for r in results if r.is_stale),
                len(results),
            )

        if len(failed) == len(results):
            raise AllSchemesFetchError(
                f"Every scheme failed to fetch and no stale fallback is available: {failed}"
            )

        return FetchSummary(
            results=results,
            all_ok=all_ok,
            failed_schemes=failed,
            changed_count=changed_count,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_session(self) -> cloudscraper.CloudScraper:
        """Create a cloudscraper session to bypass basic Cloudflare anti-bot blocks."""
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        return scraper

    def _fetch_one(
        self,
        session: Session,
        scheme: SchemeConfig,
        etag_cache: Dict[str, str],
        updated_etag_cache: Dict[str, str],
        today: str,
    ) -> FetchResult:
        """
        Fetch a single scheme page, handling all error cases and stale fallback.
        Modifies updated_etag_cache in-place on success.
        """
        # NOTE: Cleanup runs AFTER writing the new snapshot (see below) so that
        # keep_last applies to the final set including the new file (EC-P1R-002).

        try:
            html, new_etag, changed = _fetch_with_retry(
                session=session,
                scheme=scheme,
                etag_cache=etag_cache,
                timeout=self._timeout,
                max_retries=self._max_retries,
                base_delay=self._base_delay,
                min_content_bytes=self._min_content_bytes,
                allowed_domain=_ALLOWED_DOMAIN,
            )

            if not changed and html == "":
                # 304 Not Modified — load latest on-disk snapshot as stale
                return self._load_stale(scheme, new_etag, today, reason="304 Not Modified")

            # Fresh 200 content — persist snapshot, then prune old ones
            snap_path = _snapshot_path(self._raw_dir, scheme.id, today)
            snap_path.write_text(html, encoding="utf-8")
            logger.info("[%s] Snapshot written → %s", scheme.id, snap_path.name)
            _cleanup_old_snapshots(self._raw_dir, scheme.id, self._keep_last)

            if new_etag:
                updated_etag_cache[scheme.id] = new_etag

            return FetchResult(
                scheme_id=scheme.id,
                scheme_name=scheme.name,
                source_url=scheme.url,
                html=html,
                etag=new_etag,
                fetched_at=today,
                changed=changed,
                ok=True,
                snapshot_path=snap_path,
                is_stale=False,
            )

        except (WhitelistViolationError, ContentTooShortError) as exc:
            # Hard failures — log and attempt stale fallback
            logger.error("[%s] Hard fetch failure: %s", scheme.id, exc)
            return self._load_stale(scheme, etag_cache.get(scheme.id), today, reason=str(exc))

        except FetchError as exc:
            # All retries exhausted — attempt stale fallback
            logger.error("[%s] All retries exhausted: %s", scheme.id, exc)
            return self._load_stale(scheme, etag_cache.get(scheme.id), today, reason=str(exc))

    def _load_stale(
        self,
        scheme: SchemeConfig,
        etag: Optional[str],
        today: str,
        reason: str,
    ) -> FetchResult:
        """
        EC-P1F-001, EC-P1F-005: Attempt to load the most recent on-disk
        snapshot as a stale fallback when a live fetch fails.
        """
        stale_path = _latest_snapshot(self._raw_dir, scheme.id)

        if stale_path and stale_path.exists():
            html = stale_path.read_text(encoding="utf-8")
            logger.warning(
                "[%s] Using stale snapshot: %s (%s)",
                scheme.id, stale_path.name, reason,
            )
            return FetchResult(
                scheme_id=scheme.id,
                scheme_name=scheme.name,
                source_url=scheme.url,
                html=html,
                etag=etag,
                fetched_at=today,
                changed=False,
                ok=True,
                snapshot_path=stale_path,
                is_stale=True,
                error=f"Stale fallback used. Reason: {reason}",
            )

        # No stale fallback available — this scheme is completely unavailable
        logger.error(
            "[%s] No stale fallback available. Scheme data is unavailable. Reason: %s",
            scheme.id, reason,
        )
        return FetchResult(
            scheme_id=scheme.id,
            scheme_name=scheme.name,
            source_url=scheme.url,
            html="",
            etag=None,
            fetched_at=today,
            changed=False,
            ok=False,
            snapshot_path=None,
            is_stale=False,
            error=f"Fetch failed, no stale fallback. Reason: {reason}",
        )


# ---------------------------------------------------------------------------
# CLI entry point — run fetch_all directly for testing / manual refresh
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        fetcher = Fetcher()
        summary = fetcher.fetch_all()

        print("\n" + "=" * 60)
        print("  FETCH SUMMARY")
        print("=" * 60)
        for r in summary.results:
            status = "✅ OK" if r.ok else "❌ FAIL"
            stale = " [STALE]" if r.is_stale else ""
            changed = " [CHANGED]" if r.changed else ""
            print(f"  {status}{stale}{changed}  {r.scheme_id}")
            if r.error:
                print(f"           Error: {r.error}")
            if r.snapshot_path:
                print(f"           File : {r.snapshot_path.name}")

        print()
        print(f"  all_ok        : {summary.all_ok}")
        print(f"  changed_count : {summary.changed_count}")
        print(f"  failed_schemes: {summary.failed_schemes}")
        print("=" * 60)

        sys.exit(0 if summary.all_ok else 1)

    except AllSchemesFetchError as exc:
        print(f"\n❌ CRITICAL: {exc}", file=sys.stderr)
        sys.exit(2)
