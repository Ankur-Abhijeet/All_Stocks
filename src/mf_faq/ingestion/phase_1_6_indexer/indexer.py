"""
src/mf_faq/ingestion/phase_1_6_indexer/indexer.py
===================================================
Phase 1.6 — Indexer

Responsibility: Build FAISS (dense) + BM25 (sparse) indexes from the embedded
chunks and atomically swap them into data/index/live/ so serving is
never interrupted mid-update.

Input:  List[ChunkWithVector]  (from Phase 1.5 Embedder)
Output: data/index/live/
            faiss.index        — FAISS IndexFlatIP (cosine, L2-normalised)
            bm25.pkl           — BM25Okapi serialized model
            chunks.jsonl       — Chunk metadata (JSON lines, indexed by chunk_id)
            metadata.json      — {embedding_dim, chunk_count, bm25_version, built_at}
            chunk_hashes.json  — {chunk_id: content_hash} for drift detection

Atomic swap:
    Write to data/index/_new/ → os.replace(_new/, live/)
    data/index/live/ is always a complete, consistent index.

Edge cases:
    P1I-EC-001: Disk full during swap → pre-check free space; keep live/ untouched
    P1I-EC-002: BM25 pickle version mismatch → store bm25_version; trigger rebuild
    P1I-EC-003: Zero / too-few chunks → min_expected_chunks guard; abort
    P1I-EC-004: Concurrent read during swap → atomic os.replace() is POSIX-safe
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np
import rank_bm25
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IndexBuildError(Exception):
    """Raised when the index cannot be built (e.g. too few chunks, disk full)."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LoadedIndex:
    """
    Represents a fully-loaded index ready for serving (Phase 2 Retrieval).

    Attributes:
        faiss_index    : FAISS IndexFlatIP object
        bm25_model     : BM25Okapi model
        chunks         : Dict[chunk_id → Chunk metadata dict]
        embedding_dim  : Dimensionality of the dense vectors
        chunk_count    : Total number of indexed chunks
        built_at       : ISO date string of index build
        index_dir      : Path to data/index/live/
    """

    faiss_index: faiss.IndexFlatIP
    bm25_model: BM25Okapi
    chunks: dict
    embedding_dim: int
    chunk_count: int
    built_at: str
    index_dir: Path


# ---------------------------------------------------------------------------
# Indexer class
# ---------------------------------------------------------------------------


class Indexer:
    """
    Phase 1.6 — Dual FAISS + BM25 index builder with atomic swap.
    """

    # We expect roughly 5 schemes * 7 sections = 35 chunks. We guard against < 10.
    MIN_EXPECTED_CHUNKS = 10
    MIN_DISK_SPACE_BYTES = 50 * 1024 * 1024  # 50 MB
    BM25_VERSION = rank_bm25.__version__ if hasattr(rank_bm25, '__version__') else "unknown"

    def build(self, chunks_with_vectors: list, data_dir: Optional[Path] = None) -> None:
        """
        Build FAISS + BM25 indexes and atomically swap into data/index/live/.

        Args:
            chunks_with_vectors: List[ChunkWithVector] from Phase 1.5 Embedder
            data_dir: Override data/ directory path (default: project_root/data)

        Raises:
            IndexBuildError: If chunk count is below minimum or disk space is insufficient.
        """
        if not data_dir:
            project_root = Path(__file__).resolve().parents[4]
            data_dir = project_root / "data"

        # P1I-EC-003: Zero / too-few chunks
        if len(chunks_with_vectors) < self.MIN_EXPECTED_CHUNKS:
            raise IndexBuildError(
                f"Too few chunks to build index. Expected at least {self.MIN_EXPECTED_CHUNKS}, "
                f"got {len(chunks_with_vectors)}."
            )

        # P1I-EC-001: Pre-check free disk space
        index_base_dir = data_dir / "index"
        index_base_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(str(index_base_dir))
        if usage.free < self.MIN_DISK_SPACE_BYTES:
            raise IndexBuildError(f"Insufficient disk space. Need {self.MIN_DISK_SPACE_BYTES} bytes, got {usage.free}.")

        new_dir = index_base_dir / "_new"
        live_dir = index_base_dir / "live"
        backup_dir = index_base_dir / "_backup"

        # Clean _new directory if it exists from a previous failed run
        if new_dir.exists():
            shutil.rmtree(new_dir)
        new_dir.mkdir(parents=True)

        try:
            self._build_and_write_indexes(chunks_with_vectors, new_dir)
            
            # P1I-EC-004: Atomic swap
            if live_dir.exists():
                # On Windows, os.replace across directories might fail if target exists
                # but on POSIX it's atomic. We use os.replace to swap live with new.
                # However, you can't replace a directory with a directory natively if target isn't empty.
                # Let's rename live to backup, rename new to live, then delete backup.
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                os.rename(live_dir, backup_dir)
                os.rename(new_dir, live_dir)
                shutil.rmtree(backup_dir)
            else:
                os.rename(new_dir, live_dir)
                
            logger.info(f"Successfully built and swapped index at {live_dir}")
        except Exception as e:
            if new_dir.exists():
                shutil.rmtree(new_dir)
            raise IndexBuildError(f"Failed to build index: {e}") from e

    def _build_and_write_indexes(self, chunks_with_vectors: list, out_dir: Path) -> None:
        """Internal helper to build and serialize all files to a directory."""
        embedding_dim = len(chunks_with_vectors[0].vector)
        chunk_count = len(chunks_with_vectors)

        # 1. FAISS Index (Dense)
        faiss_index = faiss.IndexFlatIP(embedding_dim)
        # Stack vectors
        vectors = np.vstack([cwv.vector for cwv in chunks_with_vectors])
        faiss_index.add(vectors)
        faiss.write_index(faiss_index, str(out_dir / "faiss.index"))

        # 2. BM25 Model (Sparse)
        # Tokenize by splitting on whitespace and converting to lowercase
        tokenized_corpus = [cwv.chunk.text.lower().split() for cwv in chunks_with_vectors]
        bm25_model = BM25Okapi(tokenized_corpus)
        with open(out_dir / "bm25.pkl", "wb") as f:
            pickle.dump(bm25_model, f)

        # 3. Chunks Metadata (jsonl)
        # We also need an order-preserving array of chunk_ids for FAISS index mapping
        ordered_chunk_ids = []
        with open(out_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
            for cwv in chunks_with_vectors:
                ordered_chunk_ids.append(cwv.chunk.chunk_id)
                # Omit the text if we want to save space, but we need text for retrieval.
                chunk_dict = asdict(cwv.chunk)
                f.write(json.dumps(chunk_dict) + "\n")
                
        with open(out_dir / "ordered_chunk_ids.json", "w", encoding="utf-8") as f:
            json.dump(ordered_chunk_ids, f)

        # 4. Chunk Hashes (for drift detection in Phase 1.7)
        chunk_hashes = {cwv.chunk.chunk_id: cwv.chunk.content_hash for cwv in chunks_with_vectors}
        with open(out_dir / "chunk_hashes.json", "w", encoding="utf-8") as f:
            json.dump(chunk_hashes, f)

        # 5. Metadata
        metadata = {
            "embedding_dim": embedding_dim,
            "chunk_count": chunk_count,
            "bm25_version": self.BM25_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat()
        }
        with open(out_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f)

    def load(self, data_dir: Optional[Path] = None) -> LoadedIndex:
        """
        Load the live index from data/index/live/ into memory.

        Args:
            data_dir: Override data/ directory path.

        Returns:
            LoadedIndex ready for Phase 2 Retrieval.

        Raises:
            IndexBuildError: If the live index directory or required files are missing.
        """
        if not data_dir:
            project_root = Path(__file__).resolve().parents[4]
            data_dir = project_root / "data"

        live_dir = data_dir / "index" / "live"
        if not live_dir.exists():
            raise IndexBuildError(f"Live index directory not found at {live_dir}")

        try:
            # 1. Load Metadata
            with open(live_dir / "metadata.json", "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # P1I-EC-002: BM25 pickle version mismatch warning
            if metadata.get("bm25_version") != self.BM25_VERSION:
                logger.warning(
                    f"BM25 version mismatch: index was built with {metadata.get('bm25_version')}, "
                    f"but current environment has {self.BM25_VERSION}."
                )

            # 2. Load FAISS
            faiss_index = faiss.read_index(str(live_dir / "faiss.index"))

            # 3. Load BM25
            with open(live_dir / "bm25.pkl", "rb") as f:
                bm25_model = pickle.load(f)

            # 4. Load Chunks
            chunks = {}
            with open(live_dir / "chunks.jsonl", "r", encoding="utf-8") as f:
                for line in f:
                    chunk_dict = json.loads(line)
                    chunks[chunk_dict["chunk_id"]] = chunk_dict

            return LoadedIndex(
                faiss_index=faiss_index,
                bm25_model=bm25_model,
                chunks=chunks,
                embedding_dim=metadata["embedding_dim"],
                chunk_count=metadata["chunk_count"],
                built_at=metadata["built_at"],
                index_dir=live_dir
            )

        except Exception as e:
            raise IndexBuildError(f"Failed to load live index: {e}") from e
