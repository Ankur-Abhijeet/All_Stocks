"""
mf_faq.ingestion — Phase 1: Offline Ingestion Pipeline
========================================================

Sub-packages (one per sub-phase):

    phase_1_1_fetcher/    Phase 1.1 — HTML Fetcher           ✅ Implemented
    phase_1_2_extractor/  Phase 1.2 — HTML → Structured Text  🔲 Stub
    phase_1_3_cleaner/    Phase 1.3 — Text Normalization       🔲 Stub
    phase_1_4_chunker/    Phase 1.4 — Section-Aware Chunker    🔲 Stub
    phase_1_5_embedder/   Phase 1.5 — Dense Vector Embedder    🔲 Stub
    phase_1_6_indexer/    Phase 1.6 — FAISS + BM25 Indexer     🔲 Stub
    phase_1_7_refresh/    Phase 1.7 — Refresh & Health         🔲 Stub

Top-level shim files (fetcher.py, extractor.py, …) re-export from
their respective sub-packages for backward compatibility.

Pipeline (offline, runs via GitHub Actions weekly):
    Fetcher → Extractor → Cleaner → Chunker → Embedder → Indexer
    ↑
    Refresh & Health orchestrates all of the above
"""
