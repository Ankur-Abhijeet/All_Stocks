"""
src/mf_faq/orchestrator/intent_classifier.py
=============================================
Classifies the user's intent into FACTUAL, ADVISORY, or AMBIGUOUS.
"""

import re
from enum import Enum
from pathlib import Path
from mf_faq.config.loader import load_config

class Intent(Enum):
    FACTUAL = "FACTUAL"
    ADVISORY = "ADVISORY"
    AMBIGUOUS = "AMBIGUOUS"

class IntentClassifier:
    def __init__(self, config_dir=None):
        project_root = Path(__file__).resolve().parents[3]
        cfg_dir = Path(config_dir) if config_dir else project_root / "config"
        app_cfg = load_config(config_dir=cfg_dir)
        
        self.advisory_patterns = [
            re.compile(p, re.IGNORECASE) for p in app_cfg.refusal.advisory_patterns
        ]

    def classify(self, query: str) -> Intent:
        """
        Check query against advisory regex patterns.
        """
        for pattern in self.advisory_patterns:
            if pattern.search(query):
                return Intent.ADVISORY
        
        # If no advisory patterns match, treat as factual.
        # Ambiguous queries will naturally fail the confidence gate in retrieval.
        return Intent.FACTUAL
