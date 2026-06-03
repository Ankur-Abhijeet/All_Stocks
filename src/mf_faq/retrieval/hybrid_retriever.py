"""
src/mf_faq/retrieval/hybrid_retriever.py
=========================================
Phase 2 — Hybrid Retriever

Responsibility: Load the live index and retrieve the top-K chunks for a user query
using a blend of Dense (FAISS) and Sparse (BM25) search via Reciprocal Rank Fusion (RRF).

Core Logic:
1. Load live index (FAISS, BM25, metadata).
2. Query encoding:
   - Dense: Embed query using BAAI/bge-small-en with standard instruction.
   - Sparse: Tokenize query (lowercase, whitespace split).
3. Search:
   - Dense FAISS lookup → Top-K
   - Sparse BM25 lookup → Top-K
4. Fusion:
   - Apply RRF: score = sum(1 / (k + rank)) for each chunk.
5. Gate:
   - Filter out chunks below the CONFIDENCE_THRESHOLD.
   - Return Top-N chunks to the orchestrator.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict

import numpy as np
from sentence_transformers import SentenceTransformer

from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunk
from mf_faq.ingestion.phase_1_6_indexer.indexer import Indexer, LoadedIndex

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A Chunk returned by the retriever with its fusion score."""
    chunk: Chunk
    score: float


class ConfidenceGateError(Exception):
    """Raised when the top retrieved chunk fails the minimum confidence threshold."""


class HybridRetriever:
    """
    Executes FAISS + BM25 hybrid search and fuses results using RRF.
    """

    MODEL_NAME = "BAAI/bge-small-en"
    # bge-small-en expects this exact prefix for queries to achieve optimal retrieval
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
    
    # Retrieval parameters
    DENSE_K = 10
    SPARSE_K = 10
    RRF_K_CONSTANT = 60
    TOP_N_OUTPUT = 3
    CONFIDENCE_THRESHOLD = 0.015  # Minimum RRF score

    def __init__(self, data_dir=None):
        logger.info("Initializing Hybrid Retriever...")
        self.indexer = Indexer()
        self.index: LoadedIndex = self.indexer.load(data_dir=data_dir)
        
        # We need an ordered list of chunk IDs mapping to the FAISS integer indices.
        # The chunks dict in LoadedIndex is not strictly ordered by FAISS insertion order
        # in standard dictionaries if not careful, but actually chunks.jsonl is read sequentially.
        # Wait, the indexer writes 'ordered_chunk_ids.json' which we didn't explicitly load in Phase 1.6!
        # Let's fix that. Actually, Python dicts maintain insertion order since 3.7.
        # Since chunks.jsonl is written and read sequentially, list(self.index.chunks.keys()) matches FAISS indices!
        self.ordered_chunk_ids = list(self.index.chunks.keys())
        
        logger.info(f"Loaded index with {self.index.chunk_count} chunks.")

        try:
            self.model = SentenceTransformer(self.MODEL_NAME)
        except Exception as e:
            raise RuntimeError(f"Failed to load embedding model {self.MODEL_NAME}: {e}")

    def retrieve(self, query: str) -> List[RetrievedChunk]:
        """
        Retrieve the top-N most relevant chunks for the given query.

        Args:
            query: The natural language user query.

        Returns:
            List of RetrievedChunk objects sorted by RRF score descending.

        Raises:
            ConfidenceGateError: If no chunks meet the confidence threshold.
        """
        # 1. Sparse Search (BM25)
        tokenized_query = query.lower().split()
        bm25_scores = self.index.bm25_model.get_scores(tokenized_query)
        # Get top-K indices for BM25
        # argsort sorts ascending, so we take the last K and reverse
        sparse_top_indices = np.argsort(bm25_scores)[-self.SPARSE_K:][::-1]
        
        # 2. Dense Search (FAISS)
        # Apply BGE instruction prefix
        full_query = self.QUERY_PREFIX + query
        query_vector = self.model.encode(
            [full_query],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
        
        # faiss_scores are inner products (cosine similarity since L2 normalized)
        faiss_scores, faiss_indices = self.index.faiss_index.search(query_vector, self.DENSE_K)
        dense_top_indices = faiss_indices[0]  # First query's results

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[int, float] = defaultdict(float)

        # Process Sparse Ranks (rank is 1-indexed)
        for rank, idx in enumerate(sparse_top_indices, start=1):
            if bm25_scores[idx] > 0:  # Only fuse if there's actually a match
                rrf_scores[idx] += 1.0 / (self.RRF_K_CONSTANT + rank)

        # Process Dense Ranks
        for rank, idx in enumerate(dense_top_indices, start=1):
            if idx != -1:  # FAISS returns -1 if there aren't enough elements
                rrf_scores[idx] += 1.0 / (self.RRF_K_CONSTANT + rank)

        if not rrf_scores:
            raise ConfidenceGateError("Query yielded zero matches across both indexes.")

        # 4. Sort by merged RRF score
        sorted_indices = sorted(rrf_scores.keys(), key=lambda idx: rrf_scores[idx], reverse=True)

        # 5. Gate and Output
        results = []
        for idx in sorted_indices[:self.TOP_N_OUTPUT]:
            score = rrf_scores[idx]
            if score < self.CONFIDENCE_THRESHOLD:
                # If the current best fails the threshold, stop.
                # Since we are sorted descending, subsequent ones will also fail.
                break
                
            chunk_id = self.ordered_chunk_ids[idx]
            chunk_dict = self.index.chunks[chunk_id]
            
            # Reconstruct Chunk object
            chunk = Chunk(**chunk_dict)
            results.append(RetrievedChunk(chunk=chunk, score=score))

        if not results:
            raise ConfidenceGateError(f"Top chunk failed confidence threshold ({self.CONFIDENCE_THRESHOLD}).")

        logger.info(f"Retrieved {len(results)} chunks for query: '{query}'")
        return results
