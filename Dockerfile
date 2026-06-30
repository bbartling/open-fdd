# Multi-stage Rust Open-FDD edge image (linux/amd64 + linux/arm64 via buildx).
# Ships: bridge/commission binaries, openfdd-mcp (stdio), Cursor SDK chat relay (Node).
FROM node:22-bookworm AS dashboard
WORKDIR /app/dashboard
COPY workspace/dashboard/package.json workspace/dashboard/package-lock.json ./
RUN npm ci
COPY workspace/dashboard ./
ENV VITE_OUT_DIR=../frontend
RUN npm run build
COPY frontend/style.css /app/frontend/

FROM node:22-bookworm AS cursor-relay
WORKDIR /app/cursor-chat-relay
COPY tools/cursor-chat-relay/package.json tools/cursor-chat-relay/package-lock.json ./
RUN npm ci --omit=dev
COPY tools/cursor-chat-relay/server.mjs ./

FROM rust:1.95-bookworm AS builder
ARG CARGO_BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS}
RUN apt-get update \
  && apt-get install -y --no-install-recommends clang libclang-dev build-essential pkg-config \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY edge ./edge
COPY mcp ./mcp
RUN echo "==> release build jobs=${CARGO_BUILD_JOBS}" \
    && cargo build --release -p open_fdd_edge_prototype -p openfdd-mcp -j "${CARGO_BUILD_JOBS}"

FROM node:22-bookworm-slim AS runtime
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /usr/sbin/nologin openfdd

ARG OPENFDD_IMAGE_TAG=dev
ARG OPENFDD_BUILD_GIT_SHA=unknown
WORKDIR /app
COPY --from=builder /app/target/release/open_fdd_edge_prototype /usr/local/bin/open_fdd_edge_prototype
COPY --from=builder /app/target/release/openfdd-edge /usr/local/bin/openfdd-edge
COPY --from=builder /app/target/release/openfdd-mcp /usr/local/bin/openfdd-mcp
COPY --from=dashboard /app/frontend ./frontend
COPY --from=cursor-relay /app/cursor-chat-relay ./cursor-chat-relay

ENV FRONTEND_DIR=/app/frontend \
    PORT=8080 \
    OPENFDD_WORKSPACE=/var/openfdd/workspace \
    SERVICE_MODE=bridge \
    OFDD_CURSOR_CHAT_PORT=8787 \
    OFDD_CURSOR_CHAT_HOST=0.0.0.0 \
    OPENFDD_IMAGE_TAG=${OPENFDD_IMAGE_TAG} \
    OPENFDD_GIT_SHA=${OPENFDD_BUILD_GIT_SHA}

RUN mkdir -p /var/openfdd/workspace && chown -R openfdd:openfdd /var/openfdd/workspace /app

USER openfdd
EXPOSE 8080 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["open_fdd_edge_prototype"]
