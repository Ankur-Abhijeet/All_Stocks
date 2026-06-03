import pytest

from mf_faq.ingestion.phase_1_3_cleaner.cleaner import CleanedScheme
from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunker, ChunkIDCollisionError

@pytest.fixture
def chunker():
    return Chunker()

def test_chunker_basic(chunker):
    cleaned = CleanedScheme(
        scheme_id="hdfc_mid_cap",
        scheme_name="HDFC Mid-Cap Opportunities Fund",
        source_url="https://groww.in/test",
        sections={
            "expense_ratio": "0.8%",
            "exit_load": "1% within 1 year"
        }
    )
    
    chunks = chunker.chunk(cleaned)
    assert len(chunks) == 2
    
    # Check expense ratio chunk
    er_chunk = next(c for c in chunks if c.section_key == "expense_ratio")
    assert er_chunk.chunk_id == "hdfc_mid_cap_expense_ratio"
    assert "Scheme: HDFC Mid-Cap Opportunities Fund" in er_chunk.text
    assert "Section: expense_ratio" in er_chunk.text
    assert "Content: 0.8%" in er_chunk.text
    assert er_chunk.token_count == len(er_chunk.text.split())
    assert er_chunk.content_hash

def test_chunker_empty_section(chunker):
    cleaned = CleanedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="https://test",
        sections={
            "empty": "   ",
            "valid": "valid text"
        }
    )
    chunks = chunker.chunk(cleaned)
    assert len(chunks) == 1
    assert chunks[0].section_key == "valid"

def test_chunk_collision_error(chunker):
    cleaned = CleanedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="https://test",
        sections={
            "duplicate": "valid text"
        }
    )
    # Simulate an error by maliciously modifying the internal state during a loop 
    # Or just write a mock, but let's test it by passing duplicate keys if possible.
    # Since it's a dict, we can't have duplicate keys in Python dict.
    # We can test by calling it twice and tracking if we wanted to enforce it globally?
    # No, chunk ID collision is per `chunk` call according to the stub, though it's unique across schemes in the pipeline.
    # We can mock the dict to return same key twice.
    
    class MockDict(dict):
        def items(self):
            return [("duplicate", "text1"), ("duplicate", "text2")]
            
    cleaned.sections = MockDict()
    
    with pytest.raises(ChunkIDCollisionError, match="duplicate"):
        chunker.chunk(cleaned)
