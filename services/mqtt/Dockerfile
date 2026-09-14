# syntax=docker/dockerfile:1
FROM eclipse-mosquitto:2

COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY acl.example /mosquitto/config/acl
COPY docker-entrypoint-openfdd.sh /docker-entrypoint-openfdd.sh
RUN chmod 755 /docker-entrypoint-openfdd.sh

# Upstream image CMD is mosquitto -c /mosquitto/config/mosquitto.conf
ENTRYPOINT ["/docker-entrypoint-openfdd.sh"]
CMD ["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]

EXPOSE 8883

# Certs and merged ACL are bind-mounted at runtime from provision kits.
VOLUME ["/mosquitto/certs", "/mosquitto/data"]
