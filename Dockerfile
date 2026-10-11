# Backend image (FastAPI + ONNX models; no PyTorch).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/app/data MODEL_CACHE_DIR=/app/models
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Non-root runtime user. Only the data and model directories are writable; no recursive chown
# (that would duplicate every file into another layer and roughly double the image).
RUN useradd -m app && mkdir -p /app/data /app/models && chown app /app/data /app/models
USER app

# Bake the embedding + reranker models into the image so cold starts never download them.
# Done before copying the code, so code-only changes reuse this layer instead of re-downloading.
# Keep these in sync with EMBEDDING_MODEL / RERANKER_MODEL defaults in backend/core/config.py.
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ARG RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-6-v2
RUN python -c "import os; from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; d = os.environ['MODEL_CACHE_DIR']; TextEmbedding('${EMBEDDING_MODEL}', cache_dir=d); TextCrossEncoder('${RERANKER_MODEL}', cache_dir=d)"

COPY backend backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
