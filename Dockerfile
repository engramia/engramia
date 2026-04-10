# Multi-stage build for Engramia API
#
# Stage 1: builder — installs dependencies into a virtualenv
# Stage 2: runtime — copies only the venv, keeps image small

ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /app

# Build-time version — injected by CI so hatch-vcs can embed the correct
# version into the wheel without needing a .git directory in the build context.
ARG APP_VERSION=0.1.0

# Install build dependencies
RUN pip install --upgrade pip

COPY pyproject.toml README.md LICENSE.txt ./
COPY engramia/ ./engramia/
# SETUPTOOLS_SCM_PRETEND_VERSION tells hatch-vcs / setuptools-scm the version
# without needing a .git directory in the build context.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=${APP_VERSION} \
    pip install --no-cache-dir ".[api,openai,postgres,telemetry]"

# Stage 2: runtime
ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /app

# Build-time metadata — injected by CI (docker build --build-arg ...)
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=unknown

# OCI image labels (standard annotation keys)
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${GIT_COMMIT}"
LABEL org.opencontainers.image.created="${BUILD_TIME}"
LABEL org.opencontainers.image.title="Engramia"
LABEL org.opencontainers.image.licenses="BUSL-1.1"

# Install curl for container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user — never run services as root
RUN addgroup --gid 1001 --system engramia \
    && adduser --disabled-password --gecos "" --uid 1001 --ingroup engramia engramia

# Copy installed packages from builder — resolve Python minor version dynamically
RUN PY_SITELIB=$(python -c "import sysconfig; print(sysconfig.get_path('purelib'))") \
    && echo "$PY_SITELIB" > /tmp/py_sitelib
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY engramia/ ./engramia/
COPY alembic.ini ./

# Create data directory and set ownership before switching user
RUN mkdir -p /data/engramia_data && chown -R engramia:engramia /data /app

# Default configuration (override via env vars or docker-compose)
ENV ENGRAMIA_STORAGE=json
ENV ENGRAMIA_DATA_PATH=/data/engramia_data
ENV ENGRAMIA_HOST=0.0.0.0
ENV ENGRAMIA_PORT=8000

# Runtime version metadata — read by engramia/versioning.py
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}

# Persistent storage volume for JSON backend
VOLUME ["/data"]

EXPOSE 8000

# Drop privileges — run as non-root brain user
USER engramia

CMD ["uvicorn", "engramia.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
