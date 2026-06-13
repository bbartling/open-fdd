"""Niagara web SCRAM helpers (testable, no I/O)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import unicodedata


def prep_username(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value)).replace("=", "=3D").replace(",", "=2C")


def parse_scram(value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in value.split(","):
        if "=" in part:
            key, val = part.split("=", 1)
            out[key] = val
    return out


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def salted_password(password: str, salt_b64: str, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        unicodedata.normalize("NFKC", password).encode("utf-8"),
        base64.b64decode(salt_b64),
        int(iterations),
        dklen=32,
    )


def client_final_proof(
    *,
    username: str,
    client_nonce: str,
    server_first: str,
    password: str,
) -> tuple[str, str]:
    """Return (client_final_no_proof, proof_b64) for SCRAM final POST."""
    parsed = parse_scram(server_first)
    server_nonce = parsed.get("r") or ""
    if not server_nonce.startswith(client_nonce) or not parsed.get("s") or not parsed.get("i"):
        raise ValueError(f"Bad SCRAM server response: {server_first}")

    salted = salted_password(password, parsed["s"], int(parsed["i"]))
    client_first_bare = f"n={prep_username(username)},r={client_nonce}"
    client_final_no_proof = f"c=biws,r={server_nonce}"
    auth_message = f"{client_first_bare},{server_first},{client_final_no_proof}"
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    client_signature = hmac.new(stored_key, auth_message.encode("utf-8"), hashlib.sha256).digest()
    proof_b64 = base64.b64encode(xor_bytes(client_key, client_signature)).decode("ascii")
    return client_final_no_proof, proof_b64
