# Synthetic tenant ACL fixture for Wave U mqtt-key-mode-tenant-acl / P2c fold-in.
#
# Generate:
#   python3 scripts/security/fixtures/mqtt_tenant_acl/generate_acl.py
# Observe (content + optional live broker):
#   python3 scripts/security/mqtt_tenant_acl_observer.py --out-dir reports/security/mqtt_acl_demo
# Gate:
#   OPENFDD_MQTT_ACL_EXECUTE=1 ./scripts/nightly-ot-bench/26_security_mqtt_acl.sh
#
# No live credentials. deploy/mqtt/acl (root-owned local) is not this fixture.
