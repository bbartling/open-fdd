#!/usr/bin/env python3
"""Generate bcrypt password hashes for OFDD_*_PASSWORD_HASH environment variables."""

from __future__ import annotations

import getpass
import sys


def main() -> int:
    try:
        import bcrypt
    except ImportError:
        print(
            "bcrypt is required: pip install bcrypt (or install workspace/api/requirements.txt)",
            file=sys.stderr,
        )
        return 1
    if len(sys.argv) > 1:
        print(
            "Do not pass passwords on the command line (shell history / ps exposure).",
            file=sys.stderr,
        )
        return 1
    password = getpass.getpass("Password: ")
    if not password:
        print("empty password", file=sys.stderr)
        return 1
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    print(digest.decode("ascii"))
    print()
    print("# Set in auth.env.local, e.g.:")
    print("# OFDD_OPERATOR_PASSWORD_HASH=" + digest.decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
