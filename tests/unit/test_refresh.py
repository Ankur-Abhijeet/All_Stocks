import json
import os
import pytest
from pathlib import Path

from mf_faq.ingestion.phase_1_7_refresh.refresh import RefreshOrchestrator, DriftFreezeError, ConcurrentRunError
from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunk
from mf_faq.ingestion.phase_1_5_embedder.embedder import ChunkWithVector

@pytest.fixture
def tmp_project(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return tmp_path

@pytest.fixture
def orchestrator(tmp_project, monkeypatch):
    # Monkeypatch the data directory resolution
    orch = RefreshOrchestrator()
    orch.data_dir = tmp_project / "data"
    orch.lock_file = orch.data_dir / ".refresh.lock"
    return orch

def test_acquire_release_lock(orchestrator):
    assert not orchestrator.lock_file.exists()
    orchestrator._acquire_lock()
    assert orchestrator.lock_file.exists()
    
    with pytest.raises(ConcurrentRunError):
        orchestrator._acquire_lock()
        
    orchestrator._release_lock()
    assert not orchestrator.lock_file.exists()

def test_drift_detection_bypass_on_first_run(orchestrator):
    # Missing chunk_hashes.json, should proceed without error
    chunks = [ChunkWithVector(
        chunk=Chunk("test", "id", "name", "key", "url", "text", 5, "hash1"),
        vector=None
    )]
    orchestrator._check_drift(chunks)

def test_drift_detection_freeze(orchestrator):
    live_dir = orchestrator.data_dir / "index" / "live"
    live_dir.mkdir(parents=True)
    
    old_hashes = {
        "chunk1": "old_hash1",
        "chunk2": "old_hash2",
        "chunk3": "old_hash3",
        "chunk4": "old_hash4",
        "chunk5": "old_hash5"
    }
    with open(live_dir / "chunk_hashes.json", "w") as f:
        json.dump(old_hashes, f)
        
    # We provide 5 chunks, 2 of them changed (2/5 = 40% drift) -> should freeze!
    chunks = [
        ChunkWithVector(chunk=Chunk("chunk1", "id", "name", "key", "url", "text", 5, "old_hash1"), vector=None),
        ChunkWithVector(chunk=Chunk("chunk2", "id", "name", "key", "url", "text", 5, "new_hash_changed"), vector=None),
        ChunkWithVector(chunk=Chunk("chunk3", "id", "name", "key", "url", "text", 5, "old_hash3"), vector=None),
        ChunkWithVector(chunk=Chunk("chunk4", "id", "name", "key", "url", "text", 5, "new_hash_changed"), vector=None),
        ChunkWithVector(chunk=Chunk("chunk5", "id", "name", "key", "url", "text", 5, "old_hash5"), vector=None),
    ]
    
    with pytest.raises(DriftFreezeError, match="FREEZING PIPELINE"):
        orchestrator._check_drift(chunks)

def test_drift_detection_proceed(orchestrator):
    live_dir = orchestrator.data_dir / "index" / "live"
    live_dir.mkdir(parents=True)
    
    old_hashes = {
        "chunk1": "old_hash1",
        "chunk2": "old_hash2",
        "chunk3": "old_hash3",
        "chunk4": "old_hash4",
        "chunk5": "old_hash5",
        "chunk6": "old_hash6",
        "chunk7": "old_hash7",
        "chunk8": "old_hash8",
        "chunk9": "old_hash9",
        "chunk10": "old_hash10"
    }
    with open(live_dir / "chunk_hashes.json", "w") as f:
        json.dump(old_hashes, f)
        
    # We provide 10 chunks, 2 changed (20% drift) -> should proceed!
    chunks = []
    for i in range(1, 11):
        c_hash = "new_hash" if i <= 2 else f"old_hash{i}"
        chunks.append(ChunkWithVector(
            chunk=Chunk(f"chunk{i}", "id", "name", "key", "url", "text", 5, c_hash),
            vector=None
        ))
        
    # Should not raise
    orchestrator._check_drift(chunks)
