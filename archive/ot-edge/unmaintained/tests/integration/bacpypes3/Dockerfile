FROM python:3.12-slim

RUN pip install --no-cache-dir bacpypes3==0.0.106 ifaddr
WORKDIR /app
COPY simulator.py /app/simulator.py

ENTRYPOINT ["python", "/app/simulator.py"]
CMD ["--name", "OpenFDD-CI-BACnet", "--instance", "3456", "--address", "172.30.0.10/24"]
