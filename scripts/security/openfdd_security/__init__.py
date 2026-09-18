"""Open-FDD security probe library (stdlib-first).

Produces scoped evidence for authentication, authorization, and deployment
controls. Never claims the application is fully secure.
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "openfdd_security_report_v1"
PROFILE_REGISTRY_VERSION = "openfdd_security_profiles_v1"

STATUSES = frozenset(
    {"PASS", "FAIL", "ERROR", "BLOCKED", "SKIPPED", "NOT_APPLICABLE"}
)
PROFILES = frozenset({"live_readonly", "isolated_full", "local_open"})
SUITES = frozenset({"X", "Y", "Z", "mqtt_acl"})
