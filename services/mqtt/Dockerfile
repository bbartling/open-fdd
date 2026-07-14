# syntax=docker/dockerfile:1
FROM eclipse-mosquitto:2

COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY acl.example /mosquitto/config/acl

EXPOSE 8883

# Certs and merged ACL are bind-mounted at runtime from provision kits.
VOLUME ["/mosquitto/certs", "/mosquitto/data"]
