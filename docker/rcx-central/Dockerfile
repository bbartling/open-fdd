# OpenFDD RCx Central — analyst workstation / Docker Desktop image
# docker build -f docker/rcx-central/Dockerfile -t openfdd-rcx-central:local .

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENFDD_RCX_CENTRAL_DATA=/app/portfolio/data \
    OPENFDD_RCX_CENTRAL_CONFIG=/app/portfolio/config \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY open_fdd ./open_fdd
COPY portfolio ./portfolio

RUN pip install --upgrade pip \
    && pip install -e . \
    && pip install -r portfolio/requirements.txt

RUN mkdir -p /app/portfolio/data /app/portfolio/config /app/portfolio/data/reports

EXPOSE 8050 8060

COPY docker/rcx-central/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8060/health')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
