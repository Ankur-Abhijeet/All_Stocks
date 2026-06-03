import numpy as np
import pytest

from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunk
from mf_faq.ingestion.phase_1_5_embedder.embedder import Embedder

@pytest.fixture
def embedder():
    return Embedder()

def test_embedder_basic(embedder):
    chunk1 = Chunk(
        chunk_id="test_1",
        scheme_id="test",
        scheme_name="Test Scheme",
        section_key="test_section",
        source_url="http://test",
        text="This is a test chunk.",
        token_count=5,
        content_hash="abc"
    )
    chunk2 = Chunk(
        chunk_id="test_2",
        scheme_id="test",
        scheme_name="Test Scheme",
        section_key="test_section2",
        source_url="http://test",
        text="Another chunk.",
        token_count=2,
        content_hash="def"
    )
    
    results = embedder.embed_chunks([chunk1, chunk2])
    assert len(results) == 2
    
    # Check vector properties
    v1 = results[0].vector
    assert v1.shape == (384,)
    assert v1.dtype == np.float32
    # Check L2 normalization
    assert np.isclose(np.linalg.norm(v1), 1.0, atol=1e-5)
    
def test_embedder_empty_list(embedder):
    results = embedder.embed_chunks([])
    assert results == []
