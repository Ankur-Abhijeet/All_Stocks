"""
mf_faq.ingestion.phase_1_7_refresh
=====================================
Phase 1.7 — Refresh & Health sub-package

Responsibility: Orchestrate the full Phase 1.1 → 1.6 pipeline end-to-end.
Detects content drift via SHA-256 chunk hashes. Freezes the index and opens a
GitHub Issue when drift_ratio >= 0.30 (configurable via thresholds.yaml).

Pipeline sequence:
  Fetcher (1.1) → Extractor (1.2) → Cleaner (1.3) → Chunker (1.4)
  → Embedder (1.5) → Indexer (1.6)

Drift detection:
  content_hash per chunk compared against data/index/live/chunk_hashes.json
  drift_ratio = changed_chunks / total_chunks
    < 0.30  → proceed normally
    >= 0.30 → FREEZE: alert + keep stale index + open GitHub Issue
    = 1.00  → likely page restructure → human review required

File lock:
  data/.refresh.lock prevents concurrent GitHub Actions runs from
  writing to data/index/_new/ simultaneously (EC-P1R-003).

Triggered by:
  .github/workflows/ingest.yml  (weekly cron: Monday 02:00 UTC)
  workflow_dispatch              (manual trigger)

Edge cases:
  - Drift at exactly 0.30 boundary (EC-P1R-001)
  - Disk exhaustion from old snapshots (EC-P1R-002)
  - Concurrent GH Actions runs (EC-P1R-003)
  - Missing chunk_hashes.json on first bootstrap run (EC-P1R-004)

Status: STUB — to be implemented in Phase 1
"""
