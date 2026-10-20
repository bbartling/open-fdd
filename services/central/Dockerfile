# syntax=docker/dockerfile:1
# Product central image: Rust binary only — no Python runtime.
# PyPI / wattlab_export tooling lives outside this image (offline/third-party).
FROM rust:1.95-bookworm AS builder
ARG OPENFDD_GIT_SHA=""
ENV OPENFDD_GIT_SHA=$OPENFDD_GIT_SHA
RUN apt-get update \
  && apt-get install -y --no-install-recommends clang libclang-dev build-essential pkg-config libssl-dev \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY edge ./edge
COPY mcp ./mcp
COPY services ./services
COPY sql_rules ./sql_rules
COPY sql ./sql
COPY rule_tuning ./rule_tuning
RUN cargo build --release -p openfdd-central

FROM debian:bookworm-slim
ARG OPENFDD_GIT_SHA=""
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libssl3 \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /src/target/release/openfdd-central /usr/local/bin/openfdd-central
COPY sql_rules /app/sql_rules
COPY sql /app/sql
COPY rule_tuning /app/rule_tuning
COPY fixtures/starter /app/fixtures/starter
ENV OPENFDD_CENTRAL_HOST=0.0.0.0
ENV OPENFDD_IMAGE_NAME=ghcr.io/bbartling/openfdd-central
ENV OPENFDD_SQL_RULES_DIR=/app/sql_rules
ENV OPENFDD_SQL_ROOT=/app/sql/fdd
ENV OPENFDD_SQL_SCHEMA_DIR=/app/sql/schema
ENV OPENFDD_STARTER_PACK=/app/fixtures/starter/building_50
ENV OPENFDD_CENTRAL_PORT=8080
# OFDD-071: stamp tip SHA so /api/health → {version}+{sha} (runtime env preferred by resolve_build_version).
ENV OPENFDD_GIT_SHA=$OPENFDD_GIT_SHA
EXPOSE 8080
HEALTHCHECK CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1
ENTRYPOINT ["/usr/local/bin/openfdd-central"]
