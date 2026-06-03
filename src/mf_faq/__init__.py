"""
mf_faq — Mutual Fund FAQ Assistant
====================================
Facts-Only RAG System | Groww Use Case | HDFC Mutual Fund

Package structure mirrors the 6-phase architecture:
  mf_faq.config      — Phase 0: Config loading & validation
  mf_faq.ingestion   — Phase 1: Offline ingestion pipeline
  mf_faq.retrieval   — Phase 2: Retrieval layer
  mf_faq.orchestrator — Phase 3: Reasoning & guardrails
  mf_faq.ui          — Phase 4: FastAPI backend + static SPA
"""

__version__ = "1.0.0"
__amc__ = "HDFC Mutual Fund"
