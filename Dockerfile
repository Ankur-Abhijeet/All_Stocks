# =============================================================================
# Dockerfile — Mutual Fund FAQ Assistant
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# Pre-download embedding models into the image (no internet needed at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set Hugging Face cache directory to a folder inside /app so any user can access it
ENV HF_HOME=/app/.cache
RUN mkdir -p /app/.cache && chmod 777 /app/.cache

# Pre-cache the embedding and re-ranking models
# EC-P1EM-001: Model must be baked into the image for offline deployments
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en')"
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Copy project source
COPY config/ config/
COPY src/ src/
COPY pyproject.toml .
COPY README.md .

# Install package
RUN pip install --no-cache-dir .

# Copy data (contains phase_1_4_chunked from Git, but no index)
COPY data/ data/

# Dynamically build the FAISS and BM25 index from the chunked data
ENV PYTHONPATH=src
RUN python src/mf_faq/ingestion/build_index_from_cache.py
EXPOSE 8000

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV LOG_LEVEL=INFO

CMD uvicorn mf_faq.ui.app:app --host 0.0.0.0 --port ${PORT:-8000}
