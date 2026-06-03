"""
src/mf_faq/orchestrator/orchestrator.py
========================================
Main entry point for Phase 3: Generation & Orchestration.
"""

import logging
from typing import Dict, Any, Optional

from mf_faq.orchestrator.pii_detector import PIIDetector
from mf_faq.orchestrator.intent_classifier import IntentClassifier, Intent
from mf_faq.orchestrator.llm_client import LLMClient
from mf_faq.orchestrator.post_checker import PostChecker
from mf_faq.retrieval.hybrid_retriever import HybridRetriever, ConfidenceGateError
from mf_faq.config.loader import load_config

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self, data_dir=None, config_dir=None):
        self.app_cfg = load_config(config_dir=config_dir)
        
        self.pii_detector = PIIDetector()
        self.intent_classifier = IntentClassifier(config_dir=config_dir)
        
        # Collect allowed URLs from config
        self.allowed_urls = [scheme.url for scheme in self.app_cfg.sources.corpus]
        
        self.retriever = HybridRetriever(data_dir=data_dir)
        self.llm = LLMClient()
        self.post_checker = PostChecker(allowed_urls=self.allowed_urls)
        
        self.DONT_KNOW_RESPONSE = "I don't have a verified answer for that."
        self.RETRIEVAL_FAILURE_RESPONSE = "I couldn't find a verified factual answer for that in the official Groww documents."
        self.HARD_REJECT_RESPONSE = "I generated an answer, but it was blocked by safety filters because it contained investment advice or opinions."
        self.SOFT_FAIL_RESPONSE = "I generated an answer, but it was blocked because it failed to meet the strict factual formatting guidelines."
        self.PII_BLOCK_RESPONSE = "I cannot process queries containing personal information such as PAN, Aadhaar, account numbers, emails, or phone numbers."
        self.CANNED_REFUSAL_RESPONSE = "I am a factual assistant and cannot provide investment advice or comparisons."

    def ask(self, query: str, history: Optional[list] = None) -> Dict[str, Any]:
        """
        Process a user query through the full pipeline.
        Returns a dict: {"answer": str, "source_url": str | None}
        """
        logger.info(f"Processing query (len: {len(query)})")
        
        # 1. PII Detection
        pii = self.pii_detector.detect(query)
        if pii.detected:
            logger.warning(f"PII blocked. Types: {pii.types}")
            return {"answer": self.PII_BLOCK_RESPONSE, "source_url": None}
            
        # 2. Intent Classification
        intent = self.intent_classifier.classify(query)
        if intent == Intent.ADVISORY:
            logger.info("Advisory intent detected. Refusing.")
            # Note: We can attach the first allowed URL as per table, but "None" is safer or the generic Groww link.
            # Table says "Exactly one - matching whitelisted". For simplicity, let's just return the first scheme url.
            return {"answer": self.CANNED_REFUSAL_RESPONSE, "source_url": self.allowed_urls[0]}
            
        # 3. Retrieval
        search_query = query
        if history:
            last_user_msg = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
            if last_user_msg:
                search_query = f"{last_user_msg} {query}"
                logger.info(f"Rewrote query for retrieval: {search_query}")
                
        try:
            chunks = self.retriever.retrieve(search_query)
        except ConfidenceGateError as e:
            logger.info(f"Confidence gate failed: {e}")
            return {"answer": self.RETRIEVAL_FAILURE_RESPONSE, "source_url": None}
            
        # 4. LLM Generation
        source_url = chunks[0].chunk.source_url
        response = self.llm.generate(query, chunks, history=history)
        
        # 5. Post Checking
        # If the LLM explicitly returns the fallback message, bypass post-checking to avoid soft-fail loops
        if self.RETRIEVAL_FAILURE_RESPONSE in response:
            return {"answer": self.RETRIEVAL_FAILURE_RESPONSE, "source_url": None}
            
        passed, failures, repair = self.post_checker.check(response, source_url)
        
        if passed:
            return {"answer": response, "source_url": source_url if not self.DONT_KNOW_RESPONSE.lower() in response.lower() else None}
            
        if repair == "HARD_REJECT":
            logger.error(f"Post-check hard reject: {failures}")
            return {"answer": self.HARD_REJECT_RESPONSE, "source_url": None}
            
        # 6. Retry on soft failure
        logger.warning(f"Post-check soft fail, retrying. Failures: {failures}")
        response_retry = self.llm.generate(query, chunks, repair_instruction=repair)
        passed_retry, failures_retry, repair_retry = self.post_checker.check(response_retry, source_url)
        
        if passed_retry:
            return {"answer": response_retry, "source_url": source_url if not self.DONT_KNOW_RESPONSE.lower() in response_retry.lower() else None}
        else:
            logger.error(f"Post-check failed after retry: {failures_retry}")
            return {"answer": self.SOFT_FAIL_RESPONSE, "source_url": None}
