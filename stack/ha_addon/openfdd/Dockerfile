# Open-FDD Add-on: run API in HA add-on environment
ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG C.UTF-8
ENV PYTHONUNBUFFERED 1

RUN apk add --no-cache python3 py3-pip
COPY run.sh /
RUN chmod +x /run.sh

# Install open-fdd from PyPI or local (add COPY . /app and pip install -e /app for dev)
RUN pip3 install --no-cache-dir open-fdd

EXPOSE 8000
CMD ["/run.sh"]
