# syntax=docker/dockerfile:1
# P1-M1-A: reproducible React SPA image (npm ci + non-root nginx).

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG OPENFDD_GIT_SHA=unknown
ARG OPENFDD_WEB_VERSION=0.1.0
ENV VITE_OPENFDD_GIT_SHA=$OPENFDD_GIT_SHA
ENV VITE_OPENFDD_WEB_VERSION=$OPENFDD_WEB_VERSION
RUN npm run build \
  && printf '{"ok":true,"service":"openfdd-web","git_sha":"%s","version":"%s"}\n' \
       "$OPENFDD_GIT_SHA" "$OPENFDD_WEB_VERSION" > /app/dist/version.json

# Non-root nginx (listens on 8080).
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Read-only rootfs friendly: html owned by nginx user (UID 101).
USER root
RUN chown -R 101:0 /usr/share/nginx/html
USER 101
EXPOSE 8080
