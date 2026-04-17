# Mock OpenAI-compatible LLM server for Engramia integration tests.
# Lightweight — no ML dependencies, just FastAPI + uvicorn.

FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.115.* uvicorn[standard]==0.34.*

COPY server.py .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
