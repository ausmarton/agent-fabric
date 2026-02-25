# syntax=docker/dockerfile:1
# Multi-stage build: builder produces a wheel, runtime installs only that wheel.
#
# Build:
#   docker build -t agentic-concierge .
#   docker build --build-arg VERSION=0.1.0 -t agentic-concierge:0.1.0 .
#
# Run (against a separate Ollama instance):
#   docker run -p 8080:8080 \
#     -e CONCIERGE_CONFIG_PATH=/config/fabric.json \
#     -v $(pwd)/examples/ollama.json:/config/fabric.json:ro \
#     -v af-workspace:/data/workspace \
#     agentic-concierge
#
# See docker-compose.yml for a complete Ollama + agentic-concierge setup.

# ── Stage 1: build wheel ─────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# setuptools-scm derives the version from git tags.  When building outside a
# git repository (e.g. CI artefact or plain docker build), supply the version
# as a build argument: --build-arg VERSION=0.1.0
ARG VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

RUN pip install --no-cache-dir build

COPY pyproject.toml .
COPY src/ src/

RUN python -m build --wheel --outdir /build/dist


# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="agentic-concierge" \
      org.opencontainers.image.description="Quality-first agent orchestration framework" \
      org.opencontainers.image.source="https://github.com/ausmarton/agentic-concierge" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install the built wheel (and its dependencies) only — no build tools in runtime.
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# ── Runtime environment ───────────────────────────────────────────────────────
# CONCIERGE_CONFIG_PATH — path to your fabric config JSON inside the container.
#   Mount a config file and set this env var, or use the default (Ollama on localhost).
ENV CONCIERGE_CONFIG_PATH=""

# CONCIERGE_WORKSPACE — directory where run logs and workspace files are stored.
#   Mount a volume here to persist runs across container restarts.
ENV CONCIERGE_WORKSPACE=/data/workspace

# CONCIERGE_API_KEY — when set, every endpoint except /health requires
#   Authorization: Bearer <key>.  Leave empty to disable auth (default).
ENV CONCIERGE_API_KEY=""

VOLUME ["/data/workspace"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" \
    || exit 1

CMD ["uvicorn", "agentic_concierge.interfaces.http_api:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", \
     "--log-level", "info"]
