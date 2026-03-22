# Multi-stage build for Agent Brain API
#
# Stage 1: builder — installs dependencies into a virtualenv
# Stage 2: runtime — copies only the venv, keeps image small

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --upgrade pip

COPY pyproject.toml ./
# Install with all runtime extras (api + openai + postgres)
RUN pip install --no-cache-dir ".[api,openai,postgres]"

# Stage 2: runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY agent_brain/ ./agent_brain/
COPY alembic.ini ./

# Default configuration (override via env vars or docker-compose)
ENV BRAIN_STORAGE=json
ENV BRAIN_DATA_PATH=/data/brain_data
ENV BRAIN_HOST=0.0.0.0
ENV BRAIN_PORT=8000

# Persistent storage volume for JSON backend
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "agent_brain.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
