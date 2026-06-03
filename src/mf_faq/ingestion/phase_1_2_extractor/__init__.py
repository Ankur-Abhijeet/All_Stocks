"""
mf_faq.ingestion.phase_1_2_extractor
=======================================
Phase 1.2 — Extractor sub-package

Responsibility: Parse raw HTML snapshots into structured, section-labelled text trees.

Input:  Raw HTML string + SchemeConfig metadata  (from Phase 1.1 Fetcher)
Output: ExtractedScheme(scheme_id, url, sections: Dict[str, str], extracted_at)

Sections extracted per scheme (~7 each):
  - expense_ratio
  - exit_load
  - min_sip_amount
  - lock_in_period  (ELSS only)
  - riskometer
  - benchmark_index
  - fund_overview

Status: STUB — to be implemented in Phase 1
"""
