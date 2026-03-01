# Open-FDD Add-on: run API in HA add-on environment.
# Build from repo root: docker build -f stack/ha_addon/openfdd/Dockerfile .
# open-fdd is installed from the repo copy (no PyPI); only dependencies come from PyPI.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 py3-pip
WORKDIR /app
COPY pyproject.toml README.md MANIFEST.in ./
COPY open_fdd ./open_fdd
# Install open-fdd from this repo (not PyPI). [platform,brick] = API + DB + rdflib.
RUN pip3 install --no-cache-dir --break-system-packages -e ".[platform,brick]"

COPY stack/ha_addon/openfdd/run.sh /run.sh
RUN chmod +x /run.sh
EXPOSE 8000
CMD ["/run.sh"]
