# Phase 1.1 — Fetcher

## Responsibility

Downloads the 5 whitelisted Groww HDFC Mutual Fund scheme pages and persists raw HTML snapshots to `data/raw/` with ETag-based change detection.

## Files

| File | Description |
|---|---|
| `fetcher.py` | Full implementation — `Fetcher` class, `FetchResult`, `FetchSummary`, all helpers |
| `__init__.py` | Re-exports the public API |
| `README.md` | This file |

## Input / Output

| Direction | Description |
|---|---|
| **Input** | `config/sources.yaml` — 5 whitelisted Groww scheme URLs |
| **Output** | `data/raw/<scheme_id>_<YYYY-MM-DD>.html` — dated HTML snapshots |
| **Output** | `data/raw/etag_cache.json` — ETag cache for change detection |

## Running

```bash
# From project root
python -m mf_faq.ingestion.phase_1_1_fetcher.fetcher
```

Or via the run script:
```bash
python src/mf_faq/ingestion/phase_1_1_fetcher/run_fetcher.py
```

## Edge Cases Handled

| Code | Scenario | Behaviour |
|---|---|---|
| EC-P1F-001 | HTTP 403 Forbidden | 3 retries with exponential backoff; stale snapshot fallback |
| EC-P1F-002 | HTTP 429 Rate-Limit | Respects `Retry-After` header; sleeps exact duration |
| EC-P1F-003 | Corrupted ETag cache | Returns `{}` (full re-fetch); overwrites on next save |
| EC-P1F-004 | Redirect to non-whitelisted domain | `WhitelistViolationError`; hard-fail; stale fallback |
| EC-P1F-005 | Timeout on one page | Stale fallback; `all_ok=False` if no stale available |
| EC-P1F-006 | Empty or placeholder HTML body | `ContentTooShortError`; hard-fail; stale fallback |

## Key Design Rules

- **All-or-nothing**: if any scheme fails with no stale fallback, `all_ok=False` — caller must not proceed with index swap
- **Stale fallback**: uses latest `data/raw/<scheme_id>_*.html` when live fetch fails
- **Snapshot retention**: keeps only last 3 snapshots per scheme (configurable via `thresholds.yaml`)
- **Atomic ETag cache**: writes to `.tmp` then renames to prevent partial writes
