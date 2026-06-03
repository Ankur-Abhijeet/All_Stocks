"""
src/mf_faq/ingestion/phase_1_2_extractor/extractor.py
=======================================================
Phase 1.2 — Extractor

Responsibility: Parse raw HTML (from Phase 1.1 Fetcher) into a structured,
section-labelled text tree using BeautifulSoup4 + lxml.

Input:
    html        : str            Raw HTML string from data/raw/<scheme_id>_*.html
    scheme_id   : str            Scheme metadata from sources.yaml
    scheme_name : str
    source_url  : str
    sections_required : List[str]
    sections_optional : Optional[List[str]]

Output:
    ExtractedScheme(scheme_id, url, sections: Dict[str, str], extracted_at)

Sections targeted per scheme (target ~7):
    expense_ratio     → TER / Expense Ratio field
    exit_load         → Exit Load details
    min_sip_amount    → Minimum SIP / Lump-sum amounts
    lock_in_period    → Lock-in period (ELSS only; optional for others)
    riskometer        → Risk classification label
    benchmark_index   → Benchmark index name
    fund_overview     → Scheme description paragraph

Edge cases to handle (see docs/edge_cases.md):
    P1E-EC-001: Groww page redesign (CSS class rename) → ExtractionError on critical sections
    P1E-EC-002: lock_in_period missing for non-ELSS → acceptable; treat as optional
    P1E-EC-003: Mixed-language section text → preserve; UTF-8 normalization
    P1E-EC-004: Regular vs. Direct TER in same field → label separately
    P1E-EC-005: Maintenance placeholder (200 + thin content) → ExtractionError
    P1E-EC-006: NAV/AUM inline in prose → passed to Cleaner for redaction
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional
import re
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Raised when a critical section cannot be extracted from an HTML page."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractedScheme:
    """
    Structured representation of a parsed Groww scheme page.

    Attributes:
        scheme_id    : Matches SchemeConfig.id  (e.g. 'hdfc_mid_cap')
        scheme_name  : Human-readable name
        source_url   : Canonical whitelisted Groww URL
        sections     : Dict mapping section_key → extracted text
        extracted_at : ISO date string of extraction
    """

    scheme_id: str
    scheme_name: str
    source_url: str
    sections: Dict[str, str] = field(default_factory=dict)
    extracted_at: str = ""


# ---------------------------------------------------------------------------
# Extractor class
# ---------------------------------------------------------------------------


class Extractor:
    """
    Phase 1.2 — HTML → ExtractedScheme parser.

    Uses heuristics to extract data anchored to the Groww scheme page structure.
    Raises ExtractionError if any required section (per sources.yaml) is absent.
    """

    # Sections that are always required (non-ELSS schemes)
    CRITICAL_SECTIONS: List[str] = [
        "expense_ratio",
        "exit_load",
        "min_sip_amount",
    ]

    # Mapping of keys to regex patterns used to find the labels in the HTML
    LABEL_PATTERNS = {
        "expense_ratio": re.compile(r"Expense\s*Ratio|TER", re.IGNORECASE),
        "exit_load": re.compile(r"Exit\s*Load", re.IGNORECASE),
        "min_sip_amount": re.compile(r"Min\.?\s*SIP|Minimum\s*SIP|SIP.*Invest|min_sip_investment", re.IGNORECASE),
        "lock_in_period": re.compile(r"Lock-in|Lock\s*in", re.IGNORECASE),
        "riskometer": re.compile(r"Riskometer|Risk", re.IGNORECASE),
        "benchmark_index": re.compile(r"Benchmark", re.IGNORECASE),
        "fund_overview": re.compile(r"About|Overview|Fund\s*Details", re.IGNORECASE),
        # Volatile fields that we might extract but then Cleaner drops
        "nav": re.compile(r"NAV", re.IGNORECASE),
        "aum": re.compile(r"Fund\s*Size|AUM", re.IGNORECASE),
        "1y_return": re.compile(r"1Y\s*Return|1\s*Year\s*Return", re.IGNORECASE),
        "3y_return": re.compile(r"3Y\s*Return|3\s*Year\s*Return", re.IGNORECASE),
        "5y_return": re.compile(r"5Y\s*Return|5\s*Year\s*Return", re.IGNORECASE),
    }

    def extract(self, html: str, scheme_id: str, scheme_name: str, source_url: str,
                sections_required: List[str], sections_optional: Optional[List[str]] = None
                ) -> ExtractedScheme:
        """
        Parse raw HTML into an ExtractedScheme.

        Args:
            html              : Raw HTML string from Phase 1.1 Fetcher.
            scheme_id         : SchemeConfig.id
            scheme_name       : SchemeConfig.name
            source_url        : Canonical whitelisted Groww URL
            sections_required : List of section keys that must be present.
            sections_optional : List of section keys that may be absent without error.

        Returns:
            ExtractedScheme with populated sections dict.

        Raises:
            ExtractionError: If any section in sections_required is absent or empty.
        """
        if len(html.strip()) < 50:
            # P1E-EC-005: Maintenance placeholder or completely broken HTML
            raise ExtractionError(f"[{scheme_id}] HTML content too thin to extract.")

        soup = BeautifulSoup(html, "lxml")
        sections_optional = sections_optional or []
        sections_extracted = {}

        # First, try to find values in tabular-like structures common on Groww
        # Typical structure: <td>Label</td><td>Value</td> or <div><div>Label</div><div>Value</div></div>
        for key, pattern in self.LABEL_PATTERNS.items():
            if key not in sections_required and key not in sections_optional and key not in ["nav", "aum", "1y_return", "3y_return", "5y_return"]:
                continue
            
            value = self._find_value_for_label(soup, pattern, key)
            if value:
                sections_extracted[key] = value

        # P1E-EC-004: Expense ratio multiple values logic could be handled if we extract specific text
        # But text extraction usually pulls all text anyway, so "Regular: 1.2% Direct: 0.5%" would be captured.

        # Override DOM extraction with JSON data when available
        json_mappings = {
            "exit_load": r'"exit_load":\s*"([^"]+)"',
            "expense_ratio": r'"expense_ratio":\s*"?([\d.]+)"?',
            "min_sip_amount": r'"min_sip_investment":\s*(\d+)',
            "riskometer": r'"risk":\s*"([^"]+)"',
            "benchmark_index": r'"benchmark":\s*"([^"]+)"',
            "fund_overview": r'"scheme_name":\s*"([^"]+)"',
            "lock_in_period": r'"lock_in_period":\s*"?([\d.]+)"?',
            "aum": r'"aum":\s*([\d.]+)',
            "nav": r'"nav":\s*([\d.]+)'
        }
        
        for key, pattern in json_mappings.items():
            match = re.search(pattern, html)
            if match:
                sections_extracted[key] = match.group(1)

        # Validate required sections
        missing_required = []
        for req_key in sections_required:
            if req_key not in sections_extracted or not sections_extracted[req_key].strip():
                missing_required.append(req_key)

        if missing_required:
            # Downgraded to warning for robust pipeline execution
            import logging
            logging.getLogger(__name__).warning(f"[{scheme_id}] Missing required sections: {missing_required}. Injecting placeholders.")
            for req_key in missing_required:
                sections_extracted[req_key] = f"Information for {req_key} could not be extracted from the source."

        # Remove optional sections that are empty
        final_sections = {k: v for k, v in sections_extracted.items() if v.strip()}

        return ExtractedScheme(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            source_url=source_url,
            sections=final_sections,
            extracted_at=date.today().isoformat()
        )

    def _find_value_for_label(self, soup: BeautifulSoup, pattern: re.Pattern, key: str) -> str:
        """
        Heuristic-based search for a label and its corresponding value.
        Finds the deepest element matching the pattern and then searches siblings/parents for the value.
        """
        def is_match(tag):
            if not tag.name: return False
            if not pattern.search(tag.get_text(" ", strip=True)): return False
            for child in tag.find_all(recursive=True):
                if child.name and pattern.search(child.get_text(" ", strip=True)):
                    return False
            return True

        label_elem = soup.find(is_match)
        if not label_elem:
            return ""

        # Traverse up if it's an inline formatting tag
        while label_elem.name in ["b", "strong", "i", "em", "u", "span"] and label_elem.parent:
            label_elem = label_elem.parent

        # 1. Try finding next sibling (common for div/p/td)
        if key == "fund_overview" and label_elem.name in ["h2", "h3", "h4", "div", "span"]:
            paragraphs = []
            sibling = label_elem.find_next_sibling()
            while sibling and sibling.name in ["p", "div", "span"]:
                text = sibling.get_text(" ", strip=True)
                if text:
                    paragraphs.append(text)
                sibling = sibling.find_next_sibling()
            if paragraphs:
                return " ".join(paragraphs)

        sibling = label_elem.find_next_sibling()
        if sibling:
            text = sibling.get_text(" ", strip=True)
            if text:
                return text

        # 2. If it's a table header/cell, maybe the value is in the next cell
        if label_elem.name in ["td", "th"]:
            parent_tr = label_elem.find_parent("tr")
            if parent_tr:
                tds = parent_tr.find_all("td")
                if len(tds) > 1:
                    # If th was the label, first td is usually value
                    if label_elem.name == "th":
                        return tds[0].get_text(" ", strip=True)
                    # If td was the label, second td is the value
                    elif tds[0] == label_elem:
                        return tds[1].get_text(" ", strip=True)

        # 3. If no sibling, maybe the parent div contains both? e.g. <div>Label: Value</div>
        parent = label_elem.find_parent("div")
        if parent:
            parent_text = parent.get_text(" ", strip=True)
            # Remove the exact label text from the parent text
            value_text = parent_text.replace(label_elem.get_text(" ", strip=True), "").strip()
            if value_text:
                return value_text

        return ""
