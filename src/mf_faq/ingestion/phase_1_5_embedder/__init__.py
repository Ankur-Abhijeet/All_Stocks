"""
mf_faq.ingestion.phase_1_5_embedder
======================================
Phase 1.5 — Embedder sub-package

Responsibility: Generate dense vector representations for each chunk.

Input:  List[Chunk]  (from Phase 1.4 Chunker)
Output: List[ChunkWithVector]

Embedding models:
  Primary : BAAI/bge-small-en  (sentence-transformers, local, 384-dim)
  Fallback: text-embedding-3-small  (OpenAI API, if OPENAI_API_KEY set)

Parameters:
  - Vector dim: 384 (bge-small-en)
  - Normalization: L2 for cosine similarity
  - Batch size: 32

Edge cases:
  - Model not cached in Docker (EC-P1EM-001)
  - NaN / zero vector validation (EC-P1EM-002)
  - OpenAI rate-limit mid-batch (EC-P1EM-003)
  - Dimension mismatch after model upgrade (EC-P1EM-004)

Status: STUB — to be implemented in Phase 1
"""
