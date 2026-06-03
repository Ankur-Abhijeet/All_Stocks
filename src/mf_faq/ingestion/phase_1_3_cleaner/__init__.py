"""
mf_faq.ingestion.phase_1_3_cleaner
=====================================
Phase 1.3 — Cleaner sub-package

Responsibility: Remove boilerplate, normalize encoding, drop volatile fields
(NAV, AUM, return %) so only stable factual text enters the index.

Input:  ExtractedScheme  (from Phase 1.2 Extractor)
Output: CleanedScheme with normalized section text

Operations:
  - Strip nav bars, footers, cookie banners, JS blocks
  - Drop VOLATILE_KEYS: nav, aum, 1y_return, 3y_return, 5y_return
  - Drop FAQ section (opinionated copy)
  - Normalize ₹ / &#8377; / \\u20b9 → INR
  - Collapse whitespace; strip zero-width chars
  - Redact inline NAV / AUM patterns from prose

Status: STUB — to be implemented in Phase 1
"""
