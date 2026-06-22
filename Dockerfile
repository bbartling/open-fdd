# Fast Docker Desktop prototype: 100% Rust server + React/Plotly static UI.
# The production backend skeleton is in ./backend.
FROM rust:1.93-bookworm AS builder
WORKDIR /app
COPY edge ./edge
WORKDIR /app/edge
RUN cargo build --release --bins

FROM debian:bookworm-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/edge/target/release/open_fdd_edge_prototype /usr/local/bin/open_fdd_edge_prototype
COPY --from=builder /app/edge/target/release/openfdd_edge /usr/local/bin/openfdd_edge
COPY frontend ./frontend
ENV FRONTEND_DIR=/app/frontend
ENV PORT=8080
ENV OPENFDD_WORKSPACE=/app/workspace
EXPOSE 8080
CMD ["open_fdd_edge_prototype"]
