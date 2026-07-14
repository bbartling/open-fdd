# syntax=docker/dockerfile:1
# Open-FDD fieldbus — sole BACnet/Modbus/Haystack wire owner.

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
COPY config ./config
RUN cargo build --release -p openfdd-fieldbus

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl iproute2 libssl3 \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /src/target/release/openfdd-fieldbus /usr/local/bin/openfdd-fieldbus
COPY config/fieldbus /app/config
ENV OPENFDD_FIELDBUS_CONFIG_DIR=/app/config
ENV OPENFDD_FIELDBUS_HTTP_HOST=0.0.0.0
ENV OPENFDD_FIELDBUS_HTTP_PORT=8081
EXPOSE 8081/tcp
EXPOSE 47808/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8081/health || exit 1
ENTRYPOINT ["/usr/local/bin/openfdd-fieldbus"]
