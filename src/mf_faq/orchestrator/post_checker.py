"""
src/mf_faq/orchestrator/post_checker.py
========================================
Deterministically checks the LLM's response for compliance.
"""

import re
from typing import List, Tuple
from datetime import date

class PostChecker:
    BANNED_TOKENS = [
        "recommend", "should invest", "better than", "will outperform"
    ]
    DONT_KNOW_STR = "I don't have a verified answer for that."
    
    def __init__(self, allowed_urls: List[str]):
        self.allowed_urls = allowed_urls
        # Find URLs using regex
        self.url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')

    def check(self, response: str, source_url: str) -> Tuple[bool, List[str], str]:
        """
        Check the LLM response.
        Returns: (passed, list of failures, repair_instruction)
        """
        failures = []
        repair = []
        
        lower_resp = response.lower()
        
        # 1. Banned tokens (Hard reject)
        for token in self.BANNED_TOKENS:
            if token in lower_resp:
                failures.append(f"Banned token found: {token}")
                return False, failures, "HARD_REJECT"
                
        # Extract URLs
        urls = self.url_pattern.findall(response)
        
        # 2. Don't know check
        is_dont_know = self.DONT_KNOW_STR.lower() in lower_resp
        
        if is_dont_know:
            if len(urls) > 0:
                failures.append("URLs attached to a don't know response.")
                repair.append("DO NOT attach any URLs because you don't know the answer.")
        else:
            # 3. Factual URL check
            if len(urls) != 1:
                failures.append(f"Expected exactly 1 URL, found {len(urls)}.")
                repair.append("You MUST include EXACTLY ONE source URL.")
            elif urls[0] != source_url:
                failures.append(f"URL mismatch. Expected {source_url}, got {urls[0]}")
                return False, failures, "HARD_REJECT"
            elif urls[0] not in self.allowed_urls:
                failures.append(f"URL not in whitelist: {urls[0]}")
                return False, failures, "HARD_REJECT"
                
            # 4. Sentence count (soft)
            # Rough split by period, question mark, exclamation
            sentences = [s for s in re.split(r'[.!?]+', response) if s.strip()]
            # Subtract 1 for the URL line and 1 for the footer
            factual_sentences = len(sentences) - 2
            if factual_sentences > 10:
                failures.append(f"Too many sentences ({factual_sentences} > 10).")
                repair.append("Shorten your answer to MAXIMUM 10 sentences.")

        # 5. Footer check
        today = str(date.today())
        expected_footer = f"Last updated from sources: {today}"
        if expected_footer not in response:
            failures.append("Missing or incorrect footer.")
            repair.append(f"You MUST end your response exactly with: '{expected_footer}'")
            
        return len(failures) == 0, failures, " ".join(repair)
