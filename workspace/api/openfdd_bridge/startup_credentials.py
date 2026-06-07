"""Reject known example/default auth values in realistic deployment modes."""

from __future__ import annotations

import os

from .security import (
    auth_strict_configured,
    bacnet_writes_enabled,
    bridge_bind_is_public,
    is_production_env,
    strict_deployment_mode,
)

# Values copied from workspace/auth.env.example — must never ship to LAN/production.
KNOWN_EXAMPLE_SECRET = "local-dev-secret-min-32-characters-long"
KNOWN_EXAMPLE_PASSWORDS: frozenset[str] = frozenset(
    {
        "operator-local",
        "msi-local",
        "agent-local",
    }
)

_GENERATOR_HINT = (
    "Generate fresh secrets: python workspace/scripts/generate_auth_env.py\n"
    "Hash passwords for production: python workspace/scripts/hash_password.py 'your-password'"
)


def _env_passwords() -> list[tuple[str, str]]:
    keys = (
        "OFDD_OPERATOR_PASSWORD",
        "OFDD_INTEGRATOR_PASSWORD",
        "OFDD_AGENT_PASSWORD",
        "OFDD_WEB_PASSWORD",
    )
    return [(key, os.environ.get(key, "").strip()) for key in keys if os.environ.get(key, "").strip()]


def _env_password_hashes() -> list[str]:
    keys = (
        "OFDD_OPERATOR_PASSWORD_HASH",
        "OFDD_INTEGRATOR_PASSWORD_HASH",
        "OFDD_AGENT_PASSWORD_HASH",
    )
    return [os.environ.get(key, "").strip() for key in keys if os.environ.get(key, "").strip()]


def uses_plaintext_passwords() -> bool:
    return bool(_env_passwords())


def uses_example_credentials() -> list[str]:
    """Return human-readable list of detected example/default credential issues."""
    issues: list[str] = []
    secret = os.environ.get("OFDD_AUTH_SECRET", "").strip()
    if secret == KNOWN_EXAMPLE_SECRET:
        issues.append("OFDD_AUTH_SECRET matches auth.env.example (local-dev-secret-…)")
    for key, password in _env_passwords():
        if password in KNOWN_EXAMPLE_PASSWORDS:
            issues.append(f"{key} matches auth.env.example example password")
    return issues


def validate_startup_credentials() -> None:
    """Fail closed when example secrets/passwords are used in strict deployment modes."""
    if not auth_strict_configured():
        return
    if not strict_deployment_mode():
        return
    issues = uses_example_credentials()
    if issues:
        detail = "\n  • ".join(issues)
        raise RuntimeError(
            "Open-FDD refuses to start with example/default auth credentials in "
            f"{'production' if is_production_env() else 'LAN/write-enabled'} mode:\n"
            f"  • {detail}\n"
            f"{_GENERATOR_HINT}"
        )
    if uses_plaintext_passwords() and (is_production_env() or bacnet_writes_enabled() or bridge_bind_is_public()):
        import logging

        logging.getLogger(__name__).warning(
            "Plaintext role passwords are set — prefer OFDD_*_PASSWORD_HASH in production/LAN. "
            "Run: python workspace/scripts/hash_password.py '<password>'"
        )
