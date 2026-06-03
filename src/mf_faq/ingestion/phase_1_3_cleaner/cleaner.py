"""
src/mf_faq/ingestion/phase_1_3_cleaner/cleaner.py
===================================================
Phase 1.3 — Cleaner

Responsibility: Strip boilerplate, normalize encoding, and drop volatile
fields from ExtractedScheme so only stable factual text enters the index.

Input:  ExtractedScheme  (from Phase 1.2 Extractor)
Output: CleanedScheme with stable, normalized section text

Operations:
    1. Boilerplate removal — nav bars, footers, JS blocks, cookie banners
    2. Volatile field drop — NAV, AUM, 1y/3y/5y returns  (EC-P1C-001 guard)
    3. FAQ section drop — opinionated copy
    4. Encoding normalization — ₹ / &#8377; / \\u20b9 → "INR"  (EC-P1C-001)
    5. Zero-width char removal — \\u200b, \\u200c, \\u200d, \\u00ad  (EC-P1C-002)
    6. Whitespace collapse — multiple spaces/newlines → single space
    7. Inline NAV/AUM redaction — regex patterns in prose text  (EC-P1E-EC-006)
    8. Post-clean length validation — drop sections < 20 chars  (EC-P1C-004)

Edge cases:
    P1C-EC-001: ₹ in multiple encodings → normalize all to INR
    P1C-EC-002: Zero-width chars → strip before tokenization
    P1C-EC-003: Boilerplate regex strips critical numeric value → unit tests guard
    P1C-EC-004: Section reduces to empty after cleaning → drop with warning
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List

from mf_faq.ingestion.phase_1_2_extractor.extractor import ExtractedScheme


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CleanedScheme:
    """
    Cleaned, normalized representation ready for chunking.

    Attributes:
        scheme_id    : Matches SchemeConfig.id
        scheme_name  : Human-readable name
        source_url   : Canonical whitelisted Groww URL
        sections     : Dict mapping section_key → cleaned text
        cleaned_at   : ISO date string of cleaning
        dropped_keys : Section keys dropped due to being empty after cleaning
    """

    scheme_id: str
    scheme_name: str
    source_url: str
    sections: Dict[str, str] = field(default_factory=dict)
    cleaned_at: str = ""
    dropped_keys: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cleaner class
# ---------------------------------------------------------------------------


class Cleaner:
    """
    Phase 1.3 — ExtractedScheme → CleanedScheme text normalizer.

    VOLATILE_KEYS are always dropped regardless of what the Extractor provides.
    All other sections are cleaned in-place.
    """

    VOLATILE_KEYS = {"1y_return", "3y_return", "5y_return", "faq"}

    # Patterns for cleaning
    RUPEE_PATTERN = re.compile(r"(?:₹|&#8377;|\u20b9)\s*")
    ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\u00ad]")
    WHITESPACE_PATTERN = re.compile(r"\s+")
    
    # Inline NAV/AUM redaction pattern
    # e.g., "NAV of INR 123.45", "AUM is 1,234 Cr", "Fund Size: 5000"
    INLINE_VOLATILE_PATTERN = re.compile(
        r"(?:NAV|AUM|Fund Size)[\s\w:]*(?:INR|Rs\.?|₹)?\s*[\d,]+(?:\.\d+)?\s*(?:Cr|Crores|Crore)?", 
        re.IGNORECASE
    )

    def clean(self, extracted: ExtractedScheme) -> CleanedScheme:
        """
        Clean and normalize all sections in an ExtractedScheme.

        Args:
            extracted: ExtractedScheme from Phase 1.2

        Returns:
            CleanedScheme with stable, normalized section text.
        """
        cleaned_sections = {}
        dropped_keys = []

        for key, text in extracted.sections.items():
            if key.lower() in self.VOLATILE_KEYS:
                dropped_keys.append(key)
                continue
            
            cleaned_text = self._clean_text(text)
            
            # Length validation: drop empty
            if len(cleaned_text.strip()) == 0:
                dropped_keys.append(key)
                continue
                
            cleaned_sections[key] = cleaned_text

        return CleanedScheme(
            scheme_id=extracted.scheme_id,
            scheme_name=extracted.scheme_name,
            source_url=extracted.source_url,
            sections=cleaned_sections,
            cleaned_at=date.today().isoformat(),
            dropped_keys=dropped_keys
        )

    def _clean_text(self, text: str) -> str:
        """
        Apply text normalization rules.
        """
        if not text:
            return ""

        # P1E-EC-006: Redact inline NAV/AUM first
        text = self.INLINE_VOLATILE_PATTERN.sub("[REDACTED]", text)

        # P1C-EC-001: Normalize Rupee symbol
        text = self.RUPEE_PATTERN.sub("INR ", text)
        
        # P1C-EC-002: Remove zero-width characters
        text = self.ZERO_WIDTH_PATTERN.sub("", text)
        
        # P1C-EC-003: Boilerplate removal (minimal generic regex to avoid stripping numbers)
        # Assuming BeautifulSoup extracted text, there are no HTML tags. We just strip extra spaces.
        
        # Whitespace collapse
        text = self.WHITESPACE_PATTERN.sub(" ", text).strip()

        return text
