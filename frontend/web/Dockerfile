# syntax=docker/dockerfile:1
# P1-M1-A: reproducible React SPA image (npm ci + non-root nginx).

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG OPENFDD_GIT_SHA=unknown
ARG OPENFDD_WEB_VERSION=0.1.0
ARG OPENFDD_IMAGE_TAG=
ENV VITE_OPENFDD_GIT_SHA=$OPENFDD_GIT_SHA
ENV VITE_OPENFDD_WEB_VERSION=$OPENFDD_WEB_VERSION
RUN npm run build \
  && short="$(printf '%s' "$OPENFDD_GIT_SHA" | cut -c1-7)" \
  && image_tag="${OPENFDD_IMAGE_TAG:-sha-${short}}" \
  && printf '{"ok":true,"service":"openfdd-web","git_sha":"%s","git":"%s","version":"%s","image_tag":"%s"}\n' \
       "$OPENFDD_GIT_SHA" "$short" "$OPENFDD_WEB_VERSION" "$image_tag" > /app/dist/version.json

# Non-root nginx (listens on 8080). The nginx image entrypoint renders
# /etc/nginx/templates/*.template with envsubst before starting nginx.
# Keep Compose-compatible central:8080 as the default while allowing cloud
# runtimes such as Railway to point the same GHCR image at private service DNS.
# OPENFDD_NGINX_RESOLVER + variable proxy_pass enable lazy DNS (Railway race).
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV OPENFDD_CENTRAL_UPSTREAM=central:8080
ENV OPENFDD_NGINX_RESOLVER=auto
ENV NGINX_ENVSUBST_FILTER=OPENFDD_
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.d/15-openfdd-resolver.envsh /docker-entrypoint.d/15-openfdd-resolver.envsh
COPY --from=build /app/dist /usr/share/nginx/html
# Read-only rootfs friendly: html owned by nginx user (UID 101). Also validate
# the base image's template entrypoint and a Railway-style upstream at build time.
USER root
RUN chown -R 101:0 /usr/share/nginx/html \
  && chmod 0755 /docker-entrypoint.d/15-openfdd-resolver.envsh \
  && test -x /docker-entrypoint.d/15-openfdd-resolver.envsh \
  && test -x /docker-entrypoint.d/20-envsubst-on-templates.sh \
  && OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080 \
     OPENFDD_NGINX_RESOLVER=127.0.0.11 \
     NGINX_ENVSUBST_FILTER=OPENFDD_ \
     /docker-entrypoint.d/20-envsubst-on-templates.sh \
  && grep -q 'openfdd-central.railway.internal:8080' /etc/nginx/conf.d/default.conf \
  && grep -q 'set \$openfdd_central' /etc/nginx/conf.d/default.conf \
  && grep -q 'resolver 127.0.0.11' /etc/nginx/conf.d/default.conf \
  && rm -f /etc/nginx/conf.d/default.conf
USER 101
EXPOSE 8080
