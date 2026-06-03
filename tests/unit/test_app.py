import pytest
from fastapi.testclient import TestClient

def test_health_uninitialized(monkeypatch):
    from mf_faq.ui.app import app
    import mf_faq.ui.app
    
    class MockOrchestratorCls:
        def __init__(self):
            pass
            
    monkeypatch.setattr("mf_faq.ui.app.Orchestrator", MockOrchestratorCls)
    
    with TestClient(app) as client:
        # Force uninitialized
        mf_faq.ui.app.orchestrator = None
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "starting up or degraded"}

def test_health_initialized(monkeypatch):
    from mf_faq.ui.app import app
    import mf_faq.ui.app
    
    class MockIndex:
        chunk_count = 5
        
    class MockRetriever:
        index = MockIndex()
        
    class MockOrchestratorCls:
        def __init__(self):
            self.retriever = MockRetriever()
            
    monkeypatch.setattr("mf_faq.ui.app.Orchestrator", MockOrchestratorCls)
    
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "index_loaded": "True"}

def test_ask_factual(monkeypatch):
    from mf_faq.ui.app import app
    import mf_faq.ui.app
    
    class MockOrchestratorCls:
        PII_BLOCK_RESPONSE = "pii block"
        DONT_KNOW_RESPONSE = "dont know"
        CANNED_REFUSAL_RESPONSE = "canned refusal"
        
        def __init__(self):
            pass

        def ask(self, query):
            return {
                "answer": "This is a factual answer.\n\nSource URL: https://groww.in/test\nLast updated from sources: 2026-06-03",
                "source_url": "https://groww.in/test"
            }
            
    monkeypatch.setattr("mf_faq.ui.app.Orchestrator", MockOrchestratorCls)
    
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "What is the expense ratio?"})
        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "factual"
        assert data["answer"] == "This is a factual answer."
        assert data["footer"] == "Last updated from sources: 2026-06-03"
        assert data["source_url"] == "https://groww.in/test"

def test_ask_pii(monkeypatch):
    from mf_faq.ui.app import app
    import mf_faq.ui.app
    
    class MockOrchestratorCls:
        PII_BLOCK_RESPONSE = "pii block"
        DONT_KNOW_RESPONSE = "dont know"
        CANNED_REFUSAL_RESPONSE = "canned refusal"
        
        def __init__(self):
            pass

        def ask(self, query):
            return {
                "answer": "pii block",
                "source_url": None
            }
            
    monkeypatch.setattr("mf_faq.ui.app.Orchestrator", MockOrchestratorCls)
    
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "My PAN is ABCDE1234F."})
        assert response.status_code == 200
        data = response.json()
        assert data["route"] == "refusal"
        assert data["answer"] == "pii block"
        assert data["source_url"] is None
        assert data["footer"] is None
