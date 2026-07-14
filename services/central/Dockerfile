# syntax=docker/dockerfile:1
FROM rust:1.95-bookworm AS builder
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
COPY rule_tuning ./rule_tuning
RUN cargo build --release -p openfdd-central -p openfdd_mqtt

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libssl3 \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /src/target/release/openfdd-central /usr/local/bin/openfdd-central
COPY --from=builder /src/target/release/openfdd-provision /usr/local/bin/openfdd-provision
COPY sql_rules /app/sql_rules
COPY rule_tuning /app/rule_tuning
ENV OPENFDD_CENTRAL_HOST=0.0.0.0
ENV OPENFDD_CENTRAL_PORT=8080
EXPOSE 8080
HEALTHCHECK CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1
ENTRYPOINT ["/usr/local/bin/openfdd-central"]
