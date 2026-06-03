"""
tests/unit/test_fetcher.py
===========================
Phase 1.1 — Unit tests for the Fetcher

Tests cover:
  - Successful fresh fetch (HTTP 200)
  - 304 Not Modified → stale snapshot loaded from disk
  - EC-P1F-001 / EC-P1F-002 — HTTP 403/429 retries, backoff, stale fallback
  - EC-P1F-003 — Corrupted ETag cache
  - EC-P1F-004 — Redirect to non-whitelisted domain → WhitelistViolationError
  - EC-P1F-005 — Timeout on one page → partial failure, all_ok=False
  - EC-P1F-006 — Empty body → ContentTooShortError → stale fallback
  - ETag cache persistence
  - Old snapshot cleanup (keep_last)
  - AllSchemesFetchError when all schemes fail with no stale fallback
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mf_faq.ingestion.fetcher import (
    AllSchemesFetchError,
    ContentTooShortError,
    FetchResult,
    Fetcher,
    FetchSummary,
    WhitelistViolationError,
    _load_etag_cache,
    _latest_snapshot,
    _parse_retry_after,
    _save_etag_cache,
    _validate_content_length,
    _validate_final_url,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ALLOWED_DOMAIN = "https://groww.in/mutual-funds/"
VALID_URLS = [
    "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
]

LARGE_HTML = "<html>" + "x" * 6000 + "</html>"  # > 5000 bytes


def _make_mock_response(
    status_code: int,
    text: str = LARGE_HTML,
    url: str = VALID_URLS[0],
    etag: str | None = '"abc123"',
    retry_after: str | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.url = url
    resp.headers = {}
    if etag:
        resp.headers["ETag"] = etag
    if retry_after:
        resp.headers["Retry-After"] = retry_after
    return resp


# ---------------------------------------------------------------------------
# Unit tests: internal helpers
# ---------------------------------------------------------------------------


class TestValidateFinalUrl:
    def test_valid_url_passes(self):
        _validate_final_url(VALID_URLS[0], ALLOWED_DOMAIN, "hdfc_mid_cap")  # no exception

    def test_redirect_to_external_raises(self):
        with pytest.raises(WhitelistViolationError, match="non-whitelisted"):
            _validate_final_url("https://hdfcfund.com/some-page", ALLOWED_DOMAIN, "hdfc_mid_cap")

    def test_redirect_to_other_groww_page_raises(self):
        """Only groww.in/mutual-funds/ is allowed; other Groww paths are not."""
        with pytest.raises(WhitelistViolationError):
            _validate_final_url(
                "https://groww.in/stocks/hdfc-bank",
                ALLOWED_DOMAIN,
                "hdfc_mid_cap",
            )


class TestValidateContentLength:
    def test_long_enough_passes(self):
        _validate_content_length(LARGE_HTML, 5000, "hdfc_mid_cap")  # no exception

    def test_too_short_raises(self):
        short_html = "<html>maintenance</html>"
        with pytest.raises(ContentTooShortError, match="only"):
            _validate_content_length(short_html, 5000, "hdfc_mid_cap")

    def test_exactly_at_threshold_passes(self):
        html = "x" * 5000
        _validate_content_length(html, 5000, "hdfc_mid_cap")  # no exception


class TestParseRetryAfter:
    def test_numeric_seconds(self):
        resp = _make_mock_response(429, retry_after="30")
        assert _parse_retry_after(resp) == 30.0

    def test_missing_header_defaults_to_60(self):
        resp = _make_mock_response(429)
        resp.headers = {}
        assert _parse_retry_after(resp) == 60.0

    def test_non_numeric_defaults_to_60(self):
        resp = _make_mock_response(429, retry_after="Thu, 01 Jan 2026 00:00:00 GMT")
        # Should return 60.0 as fallback for HTTP-date format
        assert _parse_retry_after(resp) == 60.0


class TestETagCache:
    def test_load_missing_cache_returns_empty(self, tmp_path):
        cache = _load_etag_cache(tmp_path)
        assert cache == {}

    def test_save_and_reload(self, tmp_path):
        data = {"hdfc_mid_cap": '"etag1"', "hdfc_equity": '"etag2"'}
        _save_etag_cache(tmp_path, data)
        loaded = _load_etag_cache(tmp_path)
        assert loaded == data

    def test_corrupted_cache_returns_empty(self, tmp_path):
        """EC-P1F-003: Corrupted JSON cache returns empty dict (triggers full re-fetch)."""
        cache_path = tmp_path / "etag_cache.json"
        cache_path.write_text("{bad json", encoding="utf-8")
        cache = _load_etag_cache(tmp_path)
        assert cache == {}

    def test_non_dict_cache_returns_empty(self, tmp_path):
        """EC-P1F-003: Cache that is a list (not a dict) returns empty dict."""
        cache_path = tmp_path / "etag_cache.json"
        cache_path.write_text('["item1", "item2"]', encoding="utf-8")
        cache = _load_etag_cache(tmp_path)
        assert cache == {}

    def test_save_is_atomic(self, tmp_path):
        """Save uses a temp file + rename to avoid partial writes."""
        data = {"scheme": '"etag"'}
        _save_etag_cache(tmp_path, data)
        # .tmp file should not exist after save
        assert not (tmp_path / "etag_cache.json.tmp").exists()
        assert (tmp_path / "etag_cache.json").exists()


class TestLatestSnapshot:
    def test_returns_most_recent(self, tmp_path):
        (tmp_path / "hdfc_mid_cap_2026-05-01.html").touch()
        (tmp_path / "hdfc_mid_cap_2026-06-01.html").touch()
        result = _latest_snapshot(tmp_path, "hdfc_mid_cap")
        assert result is not None
        assert "2026-06-01" in result.name

    def test_returns_none_when_no_snapshots(self, tmp_path):
        result = _latest_snapshot(tmp_path, "hdfc_mid_cap")
        assert result is None

    def test_ignores_other_scheme_snapshots(self, tmp_path):
        (tmp_path / "hdfc_equity_2026-06-01.html").touch()
        result = _latest_snapshot(tmp_path, "hdfc_mid_cap")
        assert result is None


# ---------------------------------------------------------------------------
# Integration-style tests: Fetcher with mocked HTTP session
# ---------------------------------------------------------------------------


def _make_fetcher(tmp_path: Path) -> Fetcher:
    """Build a Fetcher pointing at the real config/ directory and a temp data dir."""
    project_root = Path(__file__).resolve().parents[2]
    config_dir = project_root / "config"
    fetcher = Fetcher(config_dir=config_dir, data_dir=tmp_path)
    return fetcher


class TestFetcherSuccess:
    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_fresh_fetch_all_200(self, mock_get, tmp_path):
        """All 5 pages return 200 → all_ok=True, 5 snapshots written."""
        mock_get.return_value = _make_mock_response(200, text=LARGE_HTML)
        # Patch url to be valid for each scheme
        for url in VALID_URLS:
            mock_get.return_value.url = url

        fetcher = _make_fetcher(tmp_path)
        # Patch url per call using side_effect
        responses = []
        for url in VALID_URLS:
            r = _make_mock_response(200, text=LARGE_HTML, url=url)
            responses.append(r)
        mock_get.side_effect = responses

        summary = fetcher.fetch_all()

        assert summary.all_ok is True
        assert len(summary.results) == 5
        assert summary.changed_count == 5
        assert summary.failed_schemes == []
        for r in summary.results:
            assert r.ok is True
            assert r.is_stale is False
            assert r.snapshot_path is not None
            assert r.snapshot_path.exists()

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_etag_cache_written_after_200(self, mock_get, tmp_path):
        """ETag values from 200 responses are persisted to etag_cache.json."""
        responses = []
        for i, url in enumerate(VALID_URLS):
            r = _make_mock_response(200, text=LARGE_HTML, url=url, etag=f'"etag{i}"')
            responses.append(r)
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        fetcher.fetch_all()

        raw_dir = tmp_path / "raw"
        cache = _load_etag_cache(raw_dir)
        assert len(cache) == 5
        assert '"etag0"' in cache.values()

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_304_loads_stale_snapshot(self, mock_get, tmp_path):
        """
        If server returns 304 Not Modified for all schemes,
        fetcher loads the latest on-disk snapshot and marks is_stale=True.
        """
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)

        # Pre-create stale snapshots for all 5 schemes
        scheme_ids = [
            "hdfc_mid_cap", "hdfc_equity", "hdfc_focused", "hdfc_elss", "hdfc_large_cap"
        ]
        for sid in scheme_ids:
            snap = raw_dir / f"{sid}_2026-05-01.html"
            snap.write_text(LARGE_HTML, encoding="utf-8")

        # Seed ETag cache so that If-None-Match is sent
        _save_etag_cache(raw_dir, {sid: '"cached-etag"' for sid in scheme_ids})

        responses = [_make_mock_response(304, text="", url=u) for u in VALID_URLS]
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        summary = fetcher.fetch_all()

        assert summary.all_ok is True
        assert summary.changed_count == 0
        for r in summary.results:
            assert r.ok is True
            assert r.is_stale is True
            assert r.html == LARGE_HTML


class TestFetcherEdgeCases:
    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    @patch("mf_faq.ingestion.fetcher.time.sleep")
    def test_403_exhausts_retries_uses_stale(self, mock_sleep, mock_get, tmp_path):
        """
        EC-P1F-001: 403 for one scheme exhausts retries → stale fallback loaded.
        all_ok=True because stale data is available.
        """
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        # Pre-create stale snapshot only for the first scheme
        snap = raw_dir / "hdfc_mid_cap_2026-05-01.html"
        snap.write_text(LARGE_HTML, encoding="utf-8")

        # First scheme: all retries return 403
        # Remaining 4 schemes: 200
        responses = []
        for _ in range(3):  # 3 retries for scheme 1
            r = _make_mock_response(403, text="Forbidden", url=VALID_URLS[0])
            r.headers = {}
            responses.append(r)
        for url in VALID_URLS[1:]:
            responses.append(_make_mock_response(200, text=LARGE_HTML, url=url))
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        summary = fetcher.fetch_all()

        assert summary.all_ok is True  # stale fallback makes it ok
        stale_result = next(r for r in summary.results if r.scheme_id == "hdfc_mid_cap")
        assert stale_result.is_stale is True
        assert stale_result.ok is True
        assert mock_sleep.called

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_403_no_stale_fallback_marks_scheme_failed(self, mock_get, tmp_path):
        """
        EC-P1F-001 + EC-P1F-005: 403 with no prior snapshot → ok=False.
        all_ok=False since we have 1 failed scheme.
        """
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        # No stale snapshots at all for scheme 1

        responses = []
        for _ in range(3):  # max_retries=3 for scheme 1
            r = _make_mock_response(403, text="Forbidden", url=VALID_URLS[0])
            r.headers = {}
            responses.append(r)
        for url in VALID_URLS[1:]:
            responses.append(_make_mock_response(200, text=LARGE_HTML, url=url))
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        with patch("mf_faq.ingestion.fetcher.time.sleep"):
            summary = fetcher.fetch_all()

        assert summary.all_ok is False
        assert "hdfc_mid_cap" in summary.failed_schemes
        failed = next(r for r in summary.results if r.scheme_id == "hdfc_mid_cap")
        assert failed.ok is False
        assert failed.html == ""

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    @patch("mf_faq.ingestion.fetcher.time.sleep")
    def test_429_respects_retry_after(self, mock_sleep, mock_get, tmp_path):
        """EC-P1F-002: 429 with Retry-After causes a sleep before retry."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        # First scheme: 429 once then 200; rest: 200
        responses = []
        r_429 = _make_mock_response(429, url=VALID_URLS[0], retry_after="5")
        r_429.headers["Retry-After"] = "5"
        responses.append(r_429)
        responses.append(_make_mock_response(200, text=LARGE_HTML, url=VALID_URLS[0]))
        for url in VALID_URLS[1:]:
            responses.append(_make_mock_response(200, text=LARGE_HTML, url=url))
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        summary = fetcher.fetch_all()

        assert summary.all_ok is True
        # Sleep called with 5.0 seconds for the 429 Retry-After
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert 5.0 in sleep_calls

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_redirect_to_external_uses_stale(self, mock_get, tmp_path):
        """EC-P1F-004: Redirect to non-whitelisted URL → stale fallback."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        snap = raw_dir / "hdfc_mid_cap_2026-05-01.html"
        snap.write_text(LARGE_HTML, encoding="utf-8")

        # Scheme 1: redirected to external domain
        r_external = _make_mock_response(200, url="https://hdfcfund.com/schemes", text=LARGE_HTML)
        responses = [r_external] + [
            _make_mock_response(200, text=LARGE_HTML, url=u) for u in VALID_URLS[1:]
        ]
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        summary = fetcher.fetch_all()

        # Stale fallback available → ok=True but is_stale=True
        mid_cap = next(r for r in summary.results if r.scheme_id == "hdfc_mid_cap")
        assert mid_cap.ok is True
        assert mid_cap.is_stale is True

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_empty_body_uses_stale(self, mock_get, tmp_path):
        """EC-P1F-006: 200 response with body < min_content_bytes → stale fallback."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        snap = raw_dir / "hdfc_mid_cap_2026-05-01.html"
        snap.write_text(LARGE_HTML, encoding="utf-8")

        tiny_html = "<html>maintenance</html>"  # << 5000 bytes
        r_tiny = _make_mock_response(200, text=tiny_html, url=VALID_URLS[0])
        responses = [r_tiny] + [
            _make_mock_response(200, text=LARGE_HTML, url=u) for u in VALID_URLS[1:]
        ]
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        summary = fetcher.fetch_all()

        mid_cap = next(r for r in summary.results if r.scheme_id == "hdfc_mid_cap")
        assert mid_cap.ok is True
        assert mid_cap.is_stale is True

    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_all_fail_no_stale_raises(self, mock_get, tmp_path):
        """All schemes fail with no stale fallback → AllSchemesFetchError raised."""
        responses = []
        for url in VALID_URLS:
            for _ in range(3):  # 3 retries each
                r = _make_mock_response(403, text="Forbidden", url=url)
                r.headers = {}
                responses.append(r)
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        with patch("mf_faq.ingestion.fetcher.time.sleep"):
            with pytest.raises(AllSchemesFetchError):
                fetcher.fetch_all()


class TestSnapshotCleanup:
    @patch("mf_faq.ingestion.phase_1_1_fetcher.fetcher.Session.get")
    def test_old_snapshots_deleted(self, mock_get, tmp_path):
        """
        EC-P1R-002: After a successful fetch, only keep_last=3 snapshots remain
        for each scheme.
        """
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)

        # Pre-create 5 old snapshots for scheme 1
        for i in range(1, 6):
            (raw_dir / f"hdfc_mid_cap_2026-0{i}-01.html").write_text(LARGE_HTML)

        responses = [_make_mock_response(200, text=LARGE_HTML, url=u) for u in VALID_URLS]
        mock_get.side_effect = responses

        fetcher = _make_fetcher(tmp_path)
        fetcher.fetch_all()

        remaining = list(raw_dir.glob("hdfc_mid_cap_*.html"))
        assert len(remaining) <= 3  # keep_last=3 (from thresholds.yaml)
