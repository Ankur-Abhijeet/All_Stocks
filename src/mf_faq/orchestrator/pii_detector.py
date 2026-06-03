"""
src/mf_faq/orchestrator/pii_detector.py
========================================
Detects PII in user queries to trigger an immediate block.
"""

import re
from dataclasses import dataclass
from typing import List

@dataclass
class PIIResult:
    detected: bool
    types: List[str]

class PIIDetector:
    PII_PATTERNS = {
        "pan": r"[A-Z]{5}[0-9]{4}[A-Z]",
        "aadhaar": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "phone": r"\b[6-9]\d{9}\b",
        "account": r"\b\d{9,18}\b",
    }

    def __init__(self):
        self.compiled_patterns = {k: re.compile(v) for k, v in self.PII_PATTERNS.items()}

    def detect(self, text: str) -> PIIResult:
        detected_types = []
        for pii_type, pattern in self.compiled_patterns.items():
            if pattern.search(text):
                detected_types.append(pii_type)
        
        return PIIResult(
            detected=len(detected_types) > 0,
            types=detected_types
        )
