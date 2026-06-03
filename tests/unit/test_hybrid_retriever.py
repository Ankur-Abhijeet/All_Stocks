import pytest
import numpy as np

from mf_faq.retrieval.hybrid_retriever import HybridRetriever, ConfidenceGateError

# We need a mock index and model
class MockBM25:
    def get_scores(self, tokenized_query):
        # Suppose chunk 0 and 2 are good matches
        return np.array([10.0, 0.0, 5.0, 0.0, 0.0])

class MockFAISS:
    def search(self, query_vector, k):
        # Suppose chunk 0 and 1 are good semantic matches
        # indices are 0 and 1
        scores = np.array([[0.9, 0.8, 0.5, 0.1, 0.0]])
        indices = np.array([[0, 1, 2, 3, 4]])
        return scores, indices

class MockLoadedIndex:
    def __init__(self):
        self.bm25_model = MockBM25()
        self.faiss_index = MockFAISS()
        self.chunks = {
            "chunk_0": {"chunk_id": "chunk_0", "scheme_id": "s1", "scheme_name": "S1", "section_key": "k1", "source_url": "u", "text": "t", "token_count": 1, "content_hash": "h"},
            "chunk_1": {"chunk_id": "chunk_1", "scheme_id": "s1", "scheme_name": "S1", "section_key": "k1", "source_url": "u", "text": "t", "token_count": 1, "content_hash": "h"},
            "chunk_2": {"chunk_id": "chunk_2", "scheme_id": "s1", "scheme_name": "S1", "section_key": "k1", "source_url": "u", "text": "t", "token_count": 1, "content_hash": "h"},
            "chunk_3": {"chunk_id": "chunk_3", "scheme_id": "s1", "scheme_name": "S1", "section_key": "k1", "source_url": "u", "text": "t", "token_count": 1, "content_hash": "h"},
            "chunk_4": {"chunk_id": "chunk_4", "scheme_id": "s1", "scheme_name": "S1", "section_key": "k1", "source_url": "u", "text": "t", "token_count": 1, "content_hash": "h"}
        }
        self.chunk_count = 5

class MockModel:
    def encode(self, texts, **kwargs):
        return np.array([[0.1] * 384])

@pytest.fixture
def mock_retriever(monkeypatch):
    # Mock the indexer load
    from mf_faq.ingestion.phase_1_6_indexer.indexer import Indexer
    
    def mock_load(self, *args, **kwargs):
        return MockLoadedIndex()
        
    monkeypatch.setattr(Indexer, "load", mock_load)
    
    # Mock SentenceTransformer
    import sentence_transformers
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", lambda x: MockModel())
    
    retriever = HybridRetriever(data_dir="mock")
    # For testing gate, lower threshold since mock scores are arbitrary
    retriever.CONFIDENCE_THRESHOLD = 0.001
    return retriever

def test_hybrid_retrieve_success(mock_retriever):
    results = mock_retriever.retrieve("test query")
    
    assert len(results) <= mock_retriever.TOP_N_OUTPUT
    
    # Chunk 0 should be top because it's rank 1 in BM25 (idx 0 has 10.0) 
    # AND rank 1 in FAISS (idx 0 is first in indices)
    assert results[0].chunk.chunk_id == "chunk_0"
    
def test_hybrid_retrieve_confidence_gate(mock_retriever):
    mock_retriever.CONFIDENCE_THRESHOLD = 0.99  # Impossible to reach with RRF
    with pytest.raises(ConfidenceGateError, match="failed confidence threshold"):
        mock_retriever.retrieve("test query")

def test_hybrid_retrieve_no_matches(mock_retriever):
    # If FAISS returns -1 and BM25 returns 0 for all
    class ZeroBM25:
        def get_scores(self, tokenized_query):
            return np.array([0.0, 0.0, 0.0, 0.0, 0.0])

    class ZeroFAISS:
        def search(self, query_vector, k):
            return np.array([[-1.0, -1.0, -1.0]]), np.array([[-1, -1, -1]])

    mock_retriever.index.bm25_model = ZeroBM25()
    mock_retriever.index.faiss_index = ZeroFAISS()
    
    with pytest.raises(ConfidenceGateError, match="yielded zero matches"):
        mock_retriever.retrieve("completely unrelated")
