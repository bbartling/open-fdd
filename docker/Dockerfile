# Open-FDD edge images — multi-target build from repo root:
#   docker build -f docker/Dockerfile --target bridge -t openfdd-bridge:local .
#   ./scripts/docker_build.sh

# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS dashboard
WORKDIR /src/workspace/dashboard
COPY workspace/dashboard/package.json workspace/dashboard/package-lock.json ./
RUN npm ci --omit=dev=false
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

RUN pip install -e ".[engine]" \
    && pip install -r bacnet_toolshed/requirements.txt

FROM python-base AS bridge

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')" || exit 1

CMD ["uvicorn", "openfdd_bridge.main:app", "--host", "0.0.0.0", "--port", "8765"]

FROM python-base AS bacnet

ENV OPENFDD_REPO_ROOT=/app \
    PYTHONPATH=/app \
    COMMISSION_ENV=/var/openfdd/workspace/bacnet/commissioning/commission.env \
    POINTS_CSV=/var/openfdd/workspace/bacnet/commissioning/points.csv \
    POLLS_CSV=/var/openfdd/workspace/bacnet/polls/samples.csv \
    BACNET_POLL_INTERVAL=60

COPY docker/bacnet-poll-entrypoint.sh /usr/local/bin/bacnet-poll-entrypoint.sh
COPY docker/bacnet-commission-entrypoint.sh /usr/local/bin/bacnet-commission-entrypoint.sh
RUN chmod +x /usr/local/bin/bacnet-poll-entrypoint.sh /usr/local/bin/bacnet-commission-entrypoint.sh

FROM bacnet AS bacnet-poll
ENTRYPOINT ["/usr/local/bin/bacnet-poll-entrypoint.sh"]

FROM bacnet AS commission
ENV OPENFDD_BACNET_COMMISSION_BIND=0.0.0.0 \
    OPENFDD_BACNET_COMMISSION_PORT=8767
ENTRYPOINT ["/usr/local/bin/bacnet-commission-entrypoint.sh"]

FROM python-base AS mcp-rag

RUN pip install fastapi "uvicorn[standard]" httpx

COPY workspace/mcp_rag ./workspace/mcp_rag

WORKDIR /app/workspace

ENV OPENFDD_REPO_ROOT=/app \
    OPENFDD_WORKSPACE_DIR=/var/openfdd/workspace \
    PYTHONPATH=/app/workspace:/app/workspace/api:/app \
    OFDD_MCP_RAG_INDEX_PATH=/var/openfdd/workspace/data/mcp/rag_index.json \
    OFDD_MCP_LISTEN_HOST=0.0.0.0 \
    OFDD_MCP_LISTEN_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')" || exit 1

CMD ["uvicorn", "mcp_rag.app:app", "--host", "0.0.0.0", "--port", "8090"]
