# Open-FDD edge images — multi-target build from repo root:
#   docker build -f docker/Dockerfile --target bridge -t openfdd-bridge:local .
#   ./scripts/docker_build.sh

# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS dashboard
WORKDIR /src/workspace/dashboard
COPY workspace/dashboard/package.json workspace/dashboard/package-lock.json ./
RUN npm ci
COPY workspace/dashboard ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY open_fdd ./open_fdd
COPY bacnet_toolshed ./bacnet_toolshed
COPY docker/python-security-constraints.txt /tmp/python-security-constraints.txt

RUN pip install --upgrade -r /tmp/python-security-constraints.txt \
    && pip install -e . \
    && pip install -r bacnet_toolshed/requirements.txt

FROM python-base AS bridge

ARG OPENFDD_IMAGE_TAG=local
ARG OPENFDD_BUILD_GIT_SHA=unknown
ARG OPENFDD_BUILD_TIME=
ENV OPENFDD_IMAGE_TAG=${OPENFDD_IMAGE_TAG} \
    OPENFDD_BUILD_GIT_SHA=${OPENFDD_BUILD_GIT_SHA} \
    OPENFDD_BUILD_TIME=${OPENFDD_BUILD_TIME}

COPY workspace/api/requirements.txt /tmp/bridge-requirements.txt
RUN pip install -r /tmp/bridge-requirements.txt

COPY workspace/api ./workspace/api
COPY --from=dashboard /src/workspace/api/static/app ./workspace/api/static/app

ENV OPENFDD_REPO_ROOT=/app \
    OPENFDD_WORKSPACE_DIR=/var/openfdd/workspace \
    OFDD_DESKTOP_DATA_DIR=/var/openfdd/workspace/data \
    PYTHONPATH=/app/workspace/api:/app \
    OFDD_BRIDGE_HOST=0.0.0.0 \
    OFDD_BRIDGE_PORT=8765

EXPOSE 8765

COPY docker/bridge-entrypoint.sh /usr/local/bin/bridge-entrypoint.sh
RUN chmod +x /usr/local/bin/bridge-entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')" || exit 1

ENTRYPOINT ["/usr/local/bin/bridge-entrypoint.sh"]

FROM python-base AS commission

ARG OPENFDD_IMAGE_TAG=local
ARG OPENFDD_BUILD_GIT_SHA=unknown
ARG OPENFDD_BUILD_TIME=
ENV OPENFDD_IMAGE_TAG=${OPENFDD_IMAGE_TAG} \
    OPENFDD_BUILD_GIT_SHA=${OPENFDD_BUILD_GIT_SHA} \
    OPENFDD_BUILD_TIME=${OPENFDD_BUILD_TIME}

ENV OPENFDD_BACNET_COMMISSION_BIND=0.0.0.0 \
    OPENFDD_BACNET_COMMISSION_PORT=8767

COPY docker/bacnet-commission-entrypoint.sh /usr/local/bin/bacnet-commission-entrypoint.sh
RUN chmod +x /usr/local/bin/bacnet-commission-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/bacnet-commission-entrypoint.sh"]

FROM python-base AS mcp-rag

ARG OPENFDD_IMAGE_TAG=local
ARG OPENFDD_BUILD_GIT_SHA=unknown
ARG OPENFDD_BUILD_TIME=
ENV OPENFDD_IMAGE_TAG=${OPENFDD_IMAGE_TAG} \
    OPENFDD_BUILD_GIT_SHA=${OPENFDD_BUILD_GIT_SHA} \
    OPENFDD_BUILD_TIME=${OPENFDD_BUILD_TIME}

COPY workspace/api/requirements.txt /tmp/mcp-requirements.txt
RUN pip install -r /tmp/mcp-requirements.txt

COPY workspace/mcp_rag ./workspace/mcp_rag
COPY workspace/mcp_server ./workspace/mcp_server

RUN pip install -r workspace/mcp_server/requirements.txt

WORKDIR /app/workspace

ENV OPENFDD_REPO_ROOT=/app \
    OPENFDD_WORKSPACE_DIR=/var/openfdd/workspace \
    PYTHONPATH=/app/workspace:/app/workspace/api:/app \
    OFDD_MCP_RAG_INDEX_PATH=/var/openfdd/workspace/data/mcp/rag_index.json \
    OFDD_MCP_LISTEN_HOST=0.0.0.0 \
    OFDD_MCP_LISTEN_PORT=8090 \
    OFDD_MCP_TRANSPORT=streamable-http \
    OFDD_MCP_MODE=edge

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')" || exit 1

CMD ["uvicorn", "mcp_server.asgi:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
