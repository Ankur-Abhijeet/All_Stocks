import pytest
from mf_faq.orchestrator.orchestrator import Orchestrator

def test_orchestrator_pii_block(monkeypatch):
    # Mock load_config and index load
    from mf_faq.config.loader import load_config, AppConfig, SourcesConfig, SchemeConfig, ThresholdsConfig, RefusalConfig
    
    mock_app_cfg = AppConfig(
        sources=SourcesConfig("v1", "today", "AMC", "groww.in", [SchemeConfig("id", "name", "category", "https://groww.in/mutual-funds/test", [], [])]),
        refusal=RefusalConfig("v1", "today", advisory_patterns=["should i buy"], advisory_semantic_examples=[], canned_refusal="refused", pii_block="blocked", dont_know_without_link="dont know", empty_query="empty"),
        thresholds=ThresholdsConfig(dense_top_k=10, sparse_top_k=10, rrf_k=60, rrf_merged_n=3, section_boost_factor=1.2, reranker_input_n=10, reranker_output_n=3, factual_threshold=0.5, ambiguous_threshold=0.3, token_soft_cap=200, token_overlap=0, min_expected_chunks=5, min_chunk_text_length=5, request_timeout_seconds=30, max_retries=3, retry_base_delay_seconds=2, min_content_bytes=5000, freeze_threshold=0.3, raw_snapshots_keep_last=3, max_tokens=200, temperature=0.0, max_soft_retries=1, max_question_length=200, max_concurrent_requests=5, ask_timeout_seconds=10),
        disclaimer="test",
        config_hash="abc"
    )
    monkeypatch.setattr("mf_faq.orchestrator.orchestrator.load_config", lambda config_dir: mock_app_cfg)
    monkeypatch.setattr("mf_faq.orchestrator.intent_classifier.load_config", lambda config_dir: mock_app_cfg)
    
    # Mock HybridRetriever to avoid actual loading
    class MockRetriever:
        def __init__(self, data_dir):
            pass
        def retrieve(self, query):
            pass
            
    monkeypatch.setattr("mf_faq.orchestrator.orchestrator.HybridRetriever", MockRetriever)
    
    orchestrator = Orchestrator()
    result = orchestrator.ask("My PAN is ABCDE1234F.")
    assert result["source_url"] is None
    assert "personal information" in result["answer"]

def test_orchestrator_dont_know(monkeypatch):
    from mf_faq.config.loader import load_config, AppConfig, SourcesConfig, SchemeConfig, ThresholdsConfig, RefusalConfig
    mock_app_cfg = AppConfig(
        sources=SourcesConfig("v1", "today", "AMC", "groww.in", [SchemeConfig("id", "name", "category", "https://groww.in/mutual-funds/test", [], [])]),
        refusal=RefusalConfig("v1", "today", advisory_patterns=["should i buy"], advisory_semantic_examples=[], canned_refusal="refused", pii_block="blocked", dont_know_without_link="dont know", empty_query="empty"),
        thresholds=ThresholdsConfig(dense_top_k=10, sparse_top_k=10, rrf_k=60, rrf_merged_n=3, section_boost_factor=1.2, reranker_input_n=10, reranker_output_n=3, factual_threshold=0.5, ambiguous_threshold=0.3, token_soft_cap=200, token_overlap=0, min_expected_chunks=5, min_chunk_text_length=5, request_timeout_seconds=30, max_retries=3, retry_base_delay_seconds=2, min_content_bytes=5000, freeze_threshold=0.3, raw_snapshots_keep_last=3, max_tokens=200, temperature=0.0, max_soft_retries=1, max_question_length=200, max_concurrent_requests=5, ask_timeout_seconds=10),
        disclaimer="test",
        config_hash="abc"
    )
    monkeypatch.setattr("mf_faq.orchestrator.orchestrator.load_config", lambda config_dir: mock_app_cfg)
    monkeypatch.setattr("mf_faq.orchestrator.intent_classifier.load_config", lambda config_dir: mock_app_cfg)

    class MockRetrieverFail:
        def __init__(self, data_dir):
            pass
        def retrieve(self, query):
            from mf_faq.retrieval.hybrid_retriever import ConfidenceGateError
            raise ConfidenceGateError("Failed")

    monkeypatch.setattr("mf_faq.orchestrator.orchestrator.HybridRetriever", MockRetrieverFail)
    
    orchestrator = Orchestrator()
    result = orchestrator.ask("Who won the world cup?")
    assert result["source_url"] is None
    assert "I don't have a verified answer for that." in result["answer"]
