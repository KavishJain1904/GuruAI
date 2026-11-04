# GuruAI container — works on Hugging Face Spaces (Docker SDK) or any other
# Docker host.
#
# All persistent data (users, sessions, embedded document chunks) lives in a
# Postgres database reached via DATABASE_URL. Embeddings are computed via a
# hosted Gemini API call (src/rag/embedder.py), not a local model — nothing is
# written to local disk at runtime and there is no heavy ML dependency (no
# PyTorch/sentence-transformers) to load or pre-bake, which keeps this image
# small and light enough for ordinary small-memory hosts.
FROM python:3.11-slim

# Create a non-root user (matches what HF Spaces expects; harmless elsewhere).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

# Install dependencies first so layer caching survives source edits.
COPY --chown=user:user requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

COPY --chown=user:user . .

# HF Spaces serves the container on 7860 (declared as app_port in the Space
# README). server.py reads PORT; keep the two in sync.
ENV PORT=7860
EXPOSE 7860

CMD ["python", "server.py"]
