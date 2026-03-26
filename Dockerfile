# Multi-stage build for Remanence API
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

# Create a non-root user — never run services as root
RUN addgroup --gid 1001 --system remanence \
    && adduser --disabled-password --gecos "" --uid 1001 --ingroup remanence remanence

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY remanence/ ./remanence/
COPY alembic.ini ./

# Create data directory and set ownership before switching user
RUN mkdir -p /data/remanence_data && chown -R remanence:remanence /data /app

# Default configuration (override via env vars or docker-compose)
ENV REMANENCE_STORAGE=json
ENV REMANENCE_DATA_PATH=/data/remanence_data
ENV REMANENCE_HOST=0.0.0.0
ENV REMANENCE_PORT=8000

# Persistent storage volume for JSON backend
VOLUME ["/data"]

EXPOSE 8000

# Drop privileges — run as non-root brain user
USER remanence

CMD ["uvicorn", "remanence.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
