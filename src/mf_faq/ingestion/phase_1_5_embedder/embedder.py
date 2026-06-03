"""
src/mf_faq/ingestion/phase_1_5_embedder/embedder.py
=====================================================
Phase 1.5 — Embedder

Responsibility: Generate L2-normalised dense vector representations for each
chunk using a local sentence-transformers model.

Input:  List[Chunk]          (from Phase 1.4 Chunker)
Output: List[ChunkWithVector]

Primary model : BAAI/bge-small-en  (384-dim, sentence-transformers, local)

Parameters:
    vector_dim  : 384  (bge-small-en)
    normalization: L2  (for cosine similarity via FAISS IndexFlatIP)
    batch_size  : 32

Edge cases:
    P1EM-EC-001: Model not cached in Docker → handled by downloading on init
    P1EM-EC-002: NaN / all-zero vector → validate and drop with warning
    P1EM-EC-004: Dimension mismatch after model upgrade → validation before returning
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ChunkWithVector:
    """A Chunk augmented with its dense embedding vector."""

    chunk: Chunk
    vector: np.ndarray  # shape (384,), float32, L2-normalised


# ---------------------------------------------------------------------------
# Embedder class
# ---------------------------------------------------------------------------


class Embedder:
    """
    Phase 1.5 — Chunk → ChunkWithVector dense embedding generator.
    """

    PRIMARY_MODEL = "BAAI/bge-small-en"
    VECTOR_DIM = 384
    BATCH_SIZE = 32

    def __init__(self):
        self.model = None

    def _load_model(self):
        """Lazy load the sentence-transformers model."""
        if self.model is None:
            try:
                logger.info(f"Loading embedding model: {self.PRIMARY_MODEL}")
                self.model = SentenceTransformer(self.PRIMARY_MODEL)
            except Exception as e:
                raise RuntimeError(f"Failed to load embedding model {self.PRIMARY_MODEL}: {e}")

    def embed_chunks(self, chunks: List[Chunk]) -> List[ChunkWithVector]:
        """
        Generate L2-normalised dense vectors for all chunks.

        Args:
            chunks: List[Chunk] from Phase 1.4 Chunker

        Returns:
            List[ChunkWithVector] — each chunk paired with its float32 vector.

        Raises:
            RuntimeError: If model loading fails.
        """
        if not chunks:
            return []

        self._load_model()
        
        texts = [chunk.text for chunk in chunks]
        
        # sentence-transformers outputs normalized vectors if normalize_embeddings=True
        # but let's do it explicitly to be sure.
        logger.info(f"Generating embeddings for {len(texts)} chunks in batches of {self.BATCH_SIZE}")
        embeddings = self.model.encode(
            texts,
            batch_size=self.BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True # bge-small-en requires this for cosine similarity
        )

        results = []
        for chunk, embedding in zip(chunks, embeddings):
            # P1EM-EC-002: NaN / all-zero vector check
            if np.isnan(embedding).any():
                logger.warning(f"NaN vector generated for chunk {chunk.chunk_id}. Dropping.")
                continue
            
            norm = np.linalg.norm(embedding)
            if norm == 0:
                logger.warning(f"All-zero vector generated for chunk {chunk.chunk_id}. Dropping.")
                continue
            
            # Re-normalize just in case
            normalized_emb = (embedding / norm).astype(np.float32)
            
            # P1EM-EC-004: Dimension mismatch
            if normalized_emb.shape[0] != self.VECTOR_DIM:
                logger.warning(
                    f"Dimension mismatch for chunk {chunk.chunk_id}: "
                    f"expected {self.VECTOR_DIM}, got {normalized_emb.shape[0]}. Dropping."
                )
                continue

            results.append(ChunkWithVector(chunk=chunk, vector=normalized_emb))

        return results
