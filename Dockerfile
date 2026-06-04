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

# Pre-cache the embedding and re-ranking models
# EC-P1EM-001: Model must be baked into the image for offline deployments
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en')"
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Copy project source
COPY config/ config/
COPY src/ src/
COPY pyproject.toml .
COPY README.md .

# Install package in editable mode
RUN pip install --no-cache-dir -e .

# Copy pre-built index (injected during CI/CD)
# COPY data/index/live/ data/index/live/

EXPOSE 8000

ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV LOG_LEVEL=INFO

CMD ["uvicorn", "mf_faq.ui.app:app", "--host", "0.0.0.0", "--port", "8000"]
