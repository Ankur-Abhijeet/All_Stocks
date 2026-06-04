import json
import logging
from pathlib import Path
from mf_faq.ingestion.phase_1_4_chunker.chunker import Chunk
from mf_faq.ingestion.phase_1_5_embedder.embedder import Embedder
from mf_faq.ingestion.phase_1_6_indexer.indexer import Indexer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def build_index():
    project_root = Path(__file__).resolve().parents[3]
    data_dir = project_root / "data"
    chunked_dir = data_dir / "phase_1_4_chunked"
    
    if not chunked_dir.exists():
        raise RuntimeError(f"{chunked_dir} not found. Cannot build index.")

    all_chunks = []
    for json_file in chunked_dir.glob("*.json"):
        with open(json_file, "r") as f:
            chunks_data = json.load(f)
            for chunk_data in chunks_data:
                all_chunks.append(Chunk(**chunk_data))

    if not all_chunks:
        raise RuntimeError("No chunks found. Aborting.")

    logger.info(f"Loaded {len(all_chunks)} chunks from cache. Embedding...")
    
    embedder = Embedder()
    chunks_with_vectors = embedder.embed_chunks(all_chunks)
    
    logger.info("Building FAISS and BM25 index...")
    indexer = Indexer()
    indexer.build(chunks_with_vectors, data_dir=data_dir)
    
    logger.info("Index successfully built dynamically!")

if __name__ == "__main__":
    build_index()
