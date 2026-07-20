# openfdd-ui — Streamlit vibe19 lab (replaces React/Caddy dashboard)
# Build context: services/ui/
FROM python:3.12-slim

ARG OPENFDD_GIT_SHA=unknown
ARG OPENFDD_IMAGE_TAG=local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODE=cloud \
    VIBE19_DOCKER=1 \
    OPENFDD_API_BASE=http://central:8080 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    OPENFDD_GIT_SHA=${OPENFDD_GIT_SHA} \
    OPENFDD_IMAGE_TAG=${OPENFDD_IMAGE_TAG}

LABEL org.opencontainers.image.title="openfdd-ui" \
      org.opencontainers.image.description="Open-FDD Streamlit vibe19 lab UI" \
      org.opencontainers.image.source="https://github.com/bbartling/open-fdd" \
      org.opencontainers.image.revision="${OPENFDD_GIT_SHA}"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
