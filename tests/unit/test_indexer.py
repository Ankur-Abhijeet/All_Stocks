import json
import os
import shutil
from pathlib import Path
import pytest
import numpy as np
import faiss

from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunk
from mf_faq.ingestion.phase_1_5_embedder.embedder import ChunkWithVector
from mf_faq.ingestion.phase_1_6_indexer.indexer import Indexer, IndexBuildError

@pytest.fixture
def tmp_data_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir

@pytest.fixture
def mock_chunks_with_vectors():
    # We need at least MIN_EXPECTED_CHUNKS (20) chunks
    chunks = []
    for i in range(25):
        chunk = Chunk(
            chunk_id=f"test_scheme_section_{i}",
            scheme_id="test_scheme",
            scheme_name="Test Scheme",
            section_key=f"section_{i}",
            source_url="http://test",
            text=f"This is test text number {i} for indexing.",
            token_count=8,
            content_hash=f"hash_{i}"
        )
        vector = np.random.rand(384).astype(np.float32)
        norm = np.linalg.norm(vector)
        vector = vector / norm
        chunks.append(ChunkWithVector(chunk=chunk, vector=vector))
    return chunks

@pytest.fixture
def indexer():
    return Indexer()

def test_indexer_build_success(indexer, tmp_data_dir, mock_chunks_with_vectors):
    indexer.build(mock_chunks_with_vectors, data_dir=tmp_data_dir)
    
    live_dir = tmp_data_dir / "index" / "live"
    assert live_dir.exists()
    assert (live_dir / "faiss.index").exists()
    assert (live_dir / "bm25.pkl").exists()
    assert (live_dir / "chunks.jsonl").exists()
    assert (live_dir / "metadata.json").exists()
    assert (live_dir / "chunk_hashes.json").exists()
    
    # Verify metadata
    with open(live_dir / "metadata.json", "r") as f:
        metadata = json.load(f)
        assert metadata["chunk_count"] == 25
        assert metadata["embedding_dim"] == 384
        
    # Verify FAISS
    faiss_index = faiss.read_index(str(live_dir / "faiss.index"))
    assert faiss_index.ntotal == 25

def test_indexer_build_too_few_chunks(indexer, tmp_data_dir, mock_chunks_with_vectors):
    with pytest.raises(IndexBuildError, match="Too few chunks"):
        indexer.build(mock_chunks_with_vectors[:10], data_dir=tmp_data_dir)

def test_indexer_load(indexer, tmp_data_dir, mock_chunks_with_vectors):
    indexer.build(mock_chunks_with_vectors, data_dir=tmp_data_dir)
    loaded_index = indexer.load(data_dir=tmp_data_dir)
    
    assert loaded_index.chunk_count == 25
    assert loaded_index.embedding_dim == 384
    assert len(loaded_index.chunks) == 25
    assert loaded_index.faiss_index.ntotal == 25
    assert hasattr(loaded_index.bm25_model, "corpus_size")

def test_indexer_atomic_swap(indexer, tmp_data_dir, mock_chunks_with_vectors):
    # Build first time
    indexer.build(mock_chunks_with_vectors, data_dir=tmp_data_dir)
    live_dir = tmp_data_dir / "index" / "live"
    
    # Store original stat
    orig_stat = live_dir.stat()
    
    # Build second time
    indexer.build(mock_chunks_with_vectors, data_dir=tmp_data_dir)
    
    # Verify live directory was replaced (different inode or modified time)
    # Since we rename directories, the live directory path now points to a new inode.
    new_stat = live_dir.stat()
    assert orig_stat.st_ino != new_stat.st_ino
