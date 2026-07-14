# syntax=docker/dockerfile:1
FROM node:22-bookworm AS build
WORKDIR /src
COPY workspace/dashboard/package.json workspace/dashboard/package-lock.json ./
RUN npm ci
COPY workspace/dashboard ./
# Split UI image uses /src/dist (legacy monolith still embeds ../../frontend via vite default).
ARG VITE_OUT_DIR=dist
ENV VITE_OUT_DIR=$VITE_OUT_DIR
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build && test -f dist/index.html

FROM caddy:2-alpine
COPY --from=build /src/dist /srv
COPY workspace/dashboard/Caddyfile.ui /etc/caddy/Caddyfile
EXPOSE 80
