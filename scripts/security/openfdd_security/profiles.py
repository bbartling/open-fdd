"""Profile registry: required check IDs and suite scopes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "profile_registry_v1.json"
)

# Core checks every profile expects when suites X/Y/Z run fully.
# Subset runs must set full_profile=false.
CORE_CHECKS = {
    "live_readonly": {
        "X": [
            "x.preauth.health_public",
            "x.preauth.anon_tenants_401",
            "x.preauth.anon_capabilities_401",
            "x.auth.admin_login_me",
            "x.jwt.missing_token_401",
            "x.jwt.malformed_token_401",
            "x.jwt.alg_none_rejected",
            "x.jwt.tampered_sig_rejected",
        ],
        "Y": [
            "y.authz.a_own_building_control",
            "y.authz.a_foreign_building_denied",
            "y.authz.b_own_building_control",
            "y.authz.b_foreign_building_denied",
            "y.authz.viewer_mutation_denied",
            "y.detector.always_401_invalidates_authz",
            "y.detector.empty_200_not_deny",
            "y.detector.html_200_not_deny",
            "y.detector.foreign_canary_leak",
        ],
        "Z": [
            "z.deploy.security_txt",
            "z.deploy.csp_present",
            "z.deploy.cors_disallow_evil",
            "z.detector.redirect_no_credential_forward",
        ],
    },
    "isolated_full": {
        "X": [
            "x.preauth.health_public",
            "x.preauth.anon_tenants_401",
            "x.preauth.anon_capabilities_401",
            "x.auth.admin_login_me",
            "x.auth.operator_a_login_me",
            "x.jwt.missing_token_401",
            "x.jwt.malformed_token_401",
            "x.jwt.alg_none_rejected",
            "x.jwt.tampered_sig_rejected",
            "x.jwt.expired_signed_rejected",
            "x.jwt.valid_sibling_accepted",
        ],
        "Y": [
            "y.authz.a_own_building_control",
            "y.authz.a_foreign_building_denied",
            "y.authz.b_own_building_control",
            "y.authz.b_foreign_building_denied",
            "y.authz.viewer_mutation_denied",
            "y.authz.admin_users_operator_denied",
            "y.detector.always_401_invalidates_authz",
            "y.detector.empty_200_not_deny",
            "y.detector.html_200_not_deny",
            "y.detector.foreign_canary_leak",
        ],
        "Z": [
            "z.deploy.security_txt",
            "z.deploy.csp_present",
            "z.deploy.cors_disallow_evil",
            "z.detector.redirect_no_credential_forward",
            "z.abuse.oversized_body_blocked",
        ],
    },
    "local_open": {
        "Z": [
            "z.deploy.loopback_precondition",
            "z.deploy.security_txt",
        ],
        "X": [],
        "Y": [],
    },
}


def required_check_ids(profile: str, suites: list[str]) -> list[str]:
    table = CORE_CHECKS.get(profile) or {}
    out: list[str] = []
    for s in suites:
        out.extend(table.get(s, []))
    return out


def load_registry(path: Path | None = None) -> dict[str, Any]:
    p = path or REGISTRY_PATH
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {
        "schema_version": "openfdd_security_profiles_v1",
        "profiles": CORE_CHECKS,
    }
