"""
src/mf_faq/ingestion/phase_1_7_refresh/refresh.py
===================================================
Phase 1.7 — Refresh & Health Orchestrator

Responsibility: Orchestrate the full Phase 1.1 → 1.6 ingestion pipeline and
enforce the drift-detection freeze rule before swapping the live index.

Pipeline:
    Fetcher (1.1) → Extractor (1.2) → Cleaner (1.3)
    → Chunker (1.4) → Embedder (1.5) → Indexer (1.6)

Drift detection:
    Compare new chunk content_hashes against data/index/live/chunk_hashes.json
    drift_ratio = changed_chunks / total_chunks
      < 0.30   → proceed; swap index atomically
      >= 0.30  → FREEZE: alert + keep stale index + open GitHub Issue
      = 1.00   → page restructure; human review required

File lock:
    data/.refresh.lock prevents concurrent GitHub Actions runs from
    corrupting data/index/_new/ simultaneously.

CLI:
    python -m mf_faq.ingestion.phase_1_7_refresh.refresh

Edge cases:
    P1R-EC-001: drift_ratio exactly at 0.30 → freeze (>= boundary)
    P1R-EC-002: Disk exhaustion → cleanup_old_snapshots called per scheme (handled by fetcher)
    P1R-EC-003: Concurrent GH Actions run → file lock guard
    P1R-EC-004: Missing chunk_hashes.json (first run) → all chunks are "new"; proceed
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from dataclasses import asdict

from mf_faq.config.loader import load_config
from mf_faq.ingestion.phase_1_1_fetcher.fetcher import Fetcher
from mf_faq.ingestion.phase_1_2_extractor.extractor import Extractor
from mf_faq.ingestion.phase_1_3_cleaner.cleaner import Cleaner
from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunker
from mf_faq.ingestion.phase_1_5_embedder.embedder import Embedder
from mf_faq.ingestion.phase_1_6_indexer.indexer import Indexer

logger = logging.getLogger(__name__)


class DriftFreezeError(Exception):
    """Raised when the computed drift ratio exceeds the FREEZE_THRESHOLD."""


class ConcurrentRunError(Exception):
    """Raised when a refresh is already running."""


class RefreshOrchestrator:
    """
    Phase 1.7 — End-to-end ingestion pipeline orchestrator.
    """

    def __init__(self):
        project_root = Path(__file__).resolve().parents[4]
        self.data_dir = project_root / "data"
        self.lock_file = self.data_dir / ".refresh.lock"
        
        self.app_cfg = load_config(config_dir=project_root / "config")
        # Ensure section thresholds are respected, but let's default to 0.30 if missing
        self.FREEZE_THRESHOLD = 0.30 

        # Initialize pipeline components
        self.fetcher = Fetcher()
        self.extractor = Extractor()
        self.cleaner = Cleaner()
        self.chunker = Chunker()
        self.embedder = Embedder()
        self.indexer = Indexer()

    def run(self) -> None:
        """
        Execute the full 1.1 → 1.6 pipeline.
        Applies drift detection; aborts index swap if drift >= FREEZE_THRESHOLD.
        """
        self._acquire_lock()
        try:
            self._do_run()
        finally:
            self._release_lock()

    def _do_run(self) -> None:
        logger.info("Starting ingestion pipeline run (Phases 1.1 → 1.6)")

        # Phase 1.1: Fetch
        summary = self.fetcher.fetch_all()
        if not summary.all_ok:
            logger.error("Fetch phase failed. Aborting pipeline to preserve existing index.")
            sys.exit(1)

        # Process all successfully fetched schemes
        all_chunks = []
        for result in summary.results:
            # Skip if we got no HTML
            if not result.html:
                continue

            try:
                scheme_cfg = self.app_cfg.sources.url_to_scheme[result.source_url]
                extracted = self.extractor.extract(
                    html=result.html,
                    scheme_id=result.scheme_id,
                    scheme_name=result.scheme_name,
                    source_url=result.source_url,
                    sections_required=scheme_cfg.sections_required,
                    sections_optional=scheme_cfg.sections_optional
                )

                # Store Phase 1.2 Extracted
                phase_1_2_dir = self.data_dir / "phase_1_2_extracted"
                phase_1_2_dir.mkdir(parents=True, exist_ok=True)
                with open(phase_1_2_dir / f"{result.scheme_id}.json", "w") as f:
                    json.dump(asdict(extracted), f, indent=4)

                # Phase 1.3: Clean
                cleaned = self.cleaner.clean(extracted)

                # Store Phase 1.3 Cleaned
                phase_1_3_dir = self.data_dir / "phase_1_3_cleaned"
                phase_1_3_dir.mkdir(parents=True, exist_ok=True)
                with open(phase_1_3_dir / f"{result.scheme_id}.json", "w") as f:
                    json.dump(asdict(cleaned), f, indent=4)

                # Phase 1.4: Chunk
                chunks = self.chunker.chunk(cleaned)
                all_chunks.extend(chunks)

                # Store Phase 1.4 Chunked
                phase_1_4_dir = self.data_dir / "phase_1_4_chunked"
                phase_1_4_dir.mkdir(parents=True, exist_ok=True)
                with open(phase_1_4_dir / f"{result.scheme_id}.json", "w") as f:
                    json.dump([asdict(c) for c in chunks], f, indent=4)

            except Exception as e:
                logger.error(f"Failed to process scheme {result.scheme_id}: {e}")
                # We can choose to fail the whole run if a scheme fails to process
                # Since fetch was OK, this means HTML parsing failed. Let's abort.
                raise RuntimeError(f"Pipeline processing failed for {result.scheme_id}") from e

        if not all_chunks:
            logger.error("No chunks produced from any scheme. Aborting.")
            sys.exit(1)

        # Phase 1.5: Embed
        chunks_with_vectors = self.embedder.embed_chunks(all_chunks)

        # Drift Detection
        self._check_drift(chunks_with_vectors)

        # Phase 1.6: Index
        self.indexer.build(chunks_with_vectors, data_dir=self.data_dir)
        logger.info("Pipeline run completed successfully.")

    def _check_drift(self, chunks_with_vectors: list) -> None:
        """
        Compare new chunk content_hashes against data/index/live/chunk_hashes.json.
        """
        old_hashes_path = self.data_dir / "index" / "live" / "chunk_hashes.json"
        
        if not old_hashes_path.exists():
            # P1R-EC-004: Missing chunk_hashes.json (first run)
            logger.info("No previous index found. Bypassing drift detection.")
            return

        try:
            with old_hashes_path.open("r", encoding="utf-8") as f:
                old_hashes = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read old hashes: {e}. Bypassing drift detection.")
            return

        changed_chunks = 0
        total_chunks = len(chunks_with_vectors)

        for cwv in chunks_with_vectors:
            chunk = cwv.chunk
            old_hash = old_hashes.get(chunk.chunk_id)
            if old_hash != chunk.content_hash:
                changed_chunks += 1

        drift_ratio = changed_chunks / total_chunks if total_chunks > 0 else 0.0
        
        logger.info(f"Drift detection: {changed_chunks}/{total_chunks} chunks changed ({drift_ratio:.2%}).")

        # P1R-EC-001: drift_ratio exactly at threshold -> freeze
        if drift_ratio >= self.FREEZE_THRESHOLD:
            msg = f"Drift ratio {drift_ratio:.2%} >= {self.FREEZE_THRESHOLD:.2%}. FREEZING PIPELINE."
            if drift_ratio == 1.0:
                msg += " 100% drift detected! Likely Groww page restructure."
            logger.error(msg)
            raise DriftFreezeError(msg)

    def _acquire_lock(self):
        # P1R-EC-003: Concurrent GH Actions run
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            raise ConcurrentRunError(f"Refresh is already running (lock file exists: {self.lock_file}).")
        self.lock_file.touch()

    def _release_lock(self):
        if self.lock_file.exists():
            self.lock_file.unlink()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    orchestrator = RefreshOrchestrator()
    orchestrator.run()
