# Multi-stage Rust Open-FDD edge image (linux/amd64 + linux/arm64 via buildx).
FROM node:22-bookworm AS dashboard
WORKDIR /app/dashboard
COPY workspace/dashboard/package.json workspace/dashboard/package-lock.json ./
RUN npm ci
COPY workspace/dashboard ./
ENV VITE_OUT_DIR=../frontend
RUN npm run build

FROM rust:1.93-bookworm AS builder
WORKDIR /app
COPY Cargo.toml ./
COPY edge ./edge
RUN cargo build --release --bins -p open_fdd_edge_prototype

FROM debian:bookworm-slim AS runtime
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /usr/sbin/nologin openfdd

WORKDIR /app
COPY --from=builder /app/target/release/open_fdd_edge_prototype /usr/local/bin/open_fdd_edge_prototype
COPY --from=builder /app/target/release/openfdd_edge /usr/local/bin/openfdd_edge
COPY --from=dashboard /app/frontend ./frontend

ENV FRONTEND_DIR=/app/frontend \
    PORT=8080 \
    OPENFDD_WORKSPACE=/var/openfdd/workspace \
    SERVICE_MODE=bridge

RUN mkdir -p /var/openfdd/workspace && chown -R openfdd:openfdd /var/openfdd/workspace /app

USER openfdd
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["open_fdd_edge_prototype"]
