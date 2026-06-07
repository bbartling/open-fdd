#!/usr/bin/env python3
"""Generate fresh Open-FDD auth environment variables (never use auth.env.example values)."""

from __future__ import annotations

import secrets
import string


def _token(n: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _password(n: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main() -> None:
    secret = secrets.token_urlsafe(48)
    print("# Copy to workspace/auth.env.local (gitignored). Store securely; rotate if exposed.")
    print("# WARNING: Do not commit this file. Do not paste into chat or tickets.")
    print()
    print(f"OFDD_AUTH_SECRET={secret}")
    print("OFDD_OPERATOR_USER=operator")
    print(f"OFDD_OPERATOR_PASSWORD={_password()}")
    print("OFDD_INTEGRATOR_USER=integrator")
    print(f"OFDD_INTEGRATOR_PASSWORD={_password()}")
    print("OFDD_AGENT_USER=agent")
    print(f"OFDD_AGENT_PASSWORD={_password()}")
    print()
    print("# Optional: hash passwords for production (preferred over plaintext):")
    print("# python workspace/scripts/hash_password.py '<password>'")
    print("# OFDD_OPERATOR_PASSWORD_HASH=$2b$...")
    print()
    print("# Recommended token lifetime for OT dashboards (8 hours):")
    print("# OFDD_AUTH_TTL_SEC=28800")


if __name__ == "__main__":
    main()
