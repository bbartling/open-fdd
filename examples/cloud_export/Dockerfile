# Minimal example: hit Open-FDD API, print timeseries + faults.
# Build: docker build -t openfdd-cloud-export -f examples/cloud_export/Dockerfile .
# Run:   docker run --rm -e API_BASE=http://host.docker.internal:8000 openfdd-cloud-export

FROM python:3.12-slim
RUN pip install --no-cache-dir httpx
WORKDIR /app
COPY examples/cloud_export.py .
CMD ["python", "cloud_export.py"]
