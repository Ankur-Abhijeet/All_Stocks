"""
mf_faq.ingestion.phase_1_4_chunker
=====================================
Phase 1.4 — Chunker sub-package

Responsibility: Split cleaned text into retrieval-optimised chunks with full
provenance metadata so every chunk can be traced back to its source URL.

Input:  CleanedScheme  (from Phase 1.3 Cleaner)
Output: List[Chunk]

Chunking strategy:
  - Section-aware: split at section boundaries first, then token-window
  - Soft cap: 250 tokens per chunk
  - Overlap: 30 tokens between consecutive chunks of the same section
  - Target: ~7 chunks × 5 schemes = ~35 chunks total

Chunk metadata fields:
  chunk_id, scheme_id, scheme_name, section_key, source_url,
  chunk_index, token_count, content_hash (SHA-256)

Status: STUB — to be implemented in Phase 1
"""
