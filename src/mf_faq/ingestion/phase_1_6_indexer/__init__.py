"""
mf_faq.ingestion.phase_1_6_indexer
=====================================
Phase 1.6 — Indexer sub-package

Responsibility: Build and persist the dual FAISS (dense) + BM25 (sparse) indexes
with atomic directory swap so serving is never interrupted.

Input:  List[ChunkWithVector]  (from Phase 1.5 Embedder)
Output: data/index/live/  (FAISS index + BM25 model + chunk JSON store)

Indexes:
  Dense  : FAISS IndexFlatIP  (cosine, L2-normalised vectors)
  Sparse : BM25Okapi           (rank_bm25 library)
  Store  : JSON lines          (chunk metadata lookup by chunk_id)

Atomic swap:
  Write to data/index/_new/ → os.replace() to data/index/live/
  Guarantees serving always reads a complete, consistent index.

Metadata written to data/index/live/metadata.json:
  embedding_dim, chunk_count, rank_bm25_version, built_at

Edge cases:
  - Disk full during atomic swap (EC-P1I-001)
  - BM25 pickle version mismatch (EC-P1I-002)
  - Zero chunks guard: min_expected_chunks check (EC-P1I-003)
  - Concurrent read during swap (EC-P1I-004)

Status: STUB — to be implemented in Phase 1
"""
