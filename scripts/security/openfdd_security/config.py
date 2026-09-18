"""Config loading, origin validation, and profile budgets."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import PROFILES, SUITES

ALLOWED_CONFIG_KEYS = frozenset(
    {
        "schema_version",
        "origin_allowlist",
        "tls",
        "identities",
        "fixtures",
        "profiles",
        "canaries",
        "notes",
    }
)

DEFAULT_BUDGETS = {
    "live_readonly": {
        "max_requests": 80,
        "timeout_s": 10.0,
        "deadline_s": 300.0,
        "rate_rps": 1.0,
        "allow_writes": False,
        "allow_mint": False,
        "allow_throttle": False,
    },
    "isolated_full": {
        "max_requests": 200,
        "timeout_s": 10.0,
        "deadline_s": 300.0,
        "rate_rps": 1.0,
        "allow_writes": True,  # still needs --allow-fixture-writes
        "allow_mint": True,
        "allow_throttle": True,
    },
    "local_open": {
        "max_requests": 40,
        "timeout_s": 10.0,
        "deadline_s": 180.0,
        "rate_rps": 1.0,
        "allow_writes": False,
        "allow_mint": False,
        "allow_throttle": False,
        "auth_isolation": "NOT_APPLICABLE",
    },
}


class ConfigError(ValueError):
    """Invalid harness configuration."""


@dataclass
class IdentityRef:
    alias: str
    username_env: str | None = None
    password_env: str | None = None
    role: str | None = None
    tenant_ids: list[str] = field(default_factory=list)
    # Optional path to a protected secret file (mode 0600); never CLI passwords.
    password_file: str | None = None


@dataclass
class FixtureRefs:
    tenant_a: str = "tenant_a"
    tenant_b: str = "tenant_b"
    building_a: str = "BUILDING_A"
    building_b: str = "BUILDING_B"
    equipment_a: str = "AHU_A"
    equipment_b: str = "AHU_B"
    canary_a: str = "CANARY_A_SYNTH"
    canary_b: str = "CANARY_B_SYNTH"
    nonexistent_object: str = "DOES_NOT_EXIST_Z9"


@dataclass
class ProbeConfig:
    raw: dict[str, Any]
    origin_allowlist: list[str]
    identities: dict[str, IdentityRef]
    fixtures: FixtureRefs
    tls_verify: bool = True
    tls_ca_file: str | None = None
    allow_http_loopback: bool = True
    follow_redirects: bool = False
    trust_env_proxy: bool = False
    max_body_bytes: int = 1 * 1024 * 1024


def _require_keys(data: dict[str, Any]) -> None:
    unknown = sorted(set(data) - ALLOWED_CONFIG_KEYS)
    if unknown:
        raise ConfigError(f"unknown config keys: {unknown}")


def load_config(path: str | Path) -> ProbeConfig:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config root must be an object")
    _require_keys(raw)
    if raw.get("schema_version") != "openfdd_security_fixtures_v1":
        raise ConfigError("schema_version must be openfdd_security_fixtures_v1")
    allow = raw.get("origin_allowlist")
    if not isinstance(allow, list) or not allow:
        raise ConfigError("origin_allowlist must be a non-empty list")
    for o in allow:
        validate_origin(str(o))
    tls = raw.get("tls") or {}
    idents: dict[str, IdentityRef] = {}
    for alias, spec in (raw.get("identities") or {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"identity {alias} must be an object")
        # Never allow inline secrets
        for bad in ("password", "token", "secret", "jwt"):
            if bad in spec:
                raise ConfigError(
                    f"identity {alias}: inline {bad!r} forbidden; use env refs"
                )
        idents[alias] = IdentityRef(
            alias=alias,
            username_env=spec.get("username_env"),
            password_env=spec.get("password_env"),
            role=spec.get("role"),
            tenant_ids=list(spec.get("tenant_ids") or []),
            password_file=spec.get("password_file"),
        )
    fx = raw.get("fixtures") or {}
    fixtures = FixtureRefs(
        tenant_a=fx.get("tenant_a", "tenant_a"),
        tenant_b=fx.get("tenant_b", "tenant_b"),
        building_a=fx.get("building_a", "BUILDING_A"),
        building_b=fx.get("building_b", "BUILDING_B"),
        equipment_a=fx.get("equipment_a", "AHU_A"),
        equipment_b=fx.get("equipment_b", "AHU_B"),
        canary_a=fx.get("canary_a", "CANARY_A_SYNTH"),
        canary_b=fx.get("canary_b", "CANARY_B_SYNTH"),
        nonexistent_object=fx.get("nonexistent_object", "DOES_NOT_EXIST_Z9"),
    )
    return ProbeConfig(
        raw=raw,
        origin_allowlist=[str(o).rstrip("/") for o in allow],
        identities=idents,
        fixtures=fixtures,
        tls_verify=bool(tls.get("verify", True)),
        tls_ca_file=tls.get("ca_file"),
        allow_http_loopback=bool(tls.get("allow_http_loopback", True)),
        follow_redirects=False,
        trust_env_proxy=False,
        max_body_bytes=int(tls.get("max_body_bytes", 1 * 1024 * 1024)),
    )


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_origin(origin: str) -> str:
    if not origin or "://" not in origin:
        raise ConfigError(f"invalid origin: {origin!r}")
    parsed = urlparse(origin)
    if parsed.username or parsed.password:
        raise ConfigError("URL credentials in origin are forbidden")
    if parsed.fragment:
        raise ConfigError("URL fragments in origin are forbidden")
    if parsed.query:
        raise ConfigError("query strings on base origin are forbidden")
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(f"unsupported scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ConfigError("origin missing hostname")
    # Normalize without trailing slash for comparison
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def assert_base_url_allowed(base_url: str, cfg: ProbeConfig, profile: str) -> str:
    origin = validate_origin(base_url.rstrip("/"))
    if origin not in cfg.origin_allowlist:
        raise ConfigError(
            f"base-url origin {origin!r} not in exact origin_allowlist"
        )
    parsed = urlparse(origin)
    if parsed.scheme == "http":
        if profile == "live_readonly":
            raise ConfigError("live_readonly requires https")
        if not cfg.allow_http_loopback:
            raise ConfigError("http disallowed by config")
        if parsed.hostname not in _LOOPBACK_HOSTS:
            raise ConfigError("http only permitted for loopback isolated/local")
    return origin


def resolve_password(ident: IdentityRef) -> str | None:
    if ident.password_env:
        val = os.environ.get(ident.password_env)
        if val is not None and val != "":
            return val
    if ident.password_file:
        path = Path(ident.password_file)
        if path.is_file():
            mode = path.stat().st_mode & 0o777
            if mode & 0o077:
                raise ConfigError(
                    f"password_file {path} must not be group/world readable"
                )
            return path.read_text(encoding="utf-8").strip()
    return None


def resolve_username(ident: IdentityRef, default: str | None = None) -> str | None:
    if ident.username_env:
        return os.environ.get(ident.username_env) or default
    return default


def budget_for(profile: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ConfigError(f"unknown profile: {profile}")
    out = dict(DEFAULT_BUDGETS[profile])
    if overrides:
        for k, v in overrides.items():
            if k in out:
                out[k] = v
    return out


def validate_profile_suite(profile: str, suites: list[str] | None) -> list[str]:
    if profile not in PROFILES:
        raise ConfigError(f"unknown profile: {profile}")
    if suites is None:
        # Full profile default suites
        if profile == "local_open":
            return ["Z"]
        if profile == "live_readonly":
            return ["X", "Y", "Z"]
        return ["X", "Y", "Z"]
    out = []
    for s in suites:
        su = s.upper() if s.lower() != "mqtt_acl" else "mqtt_acl"
        if su not in SUITES and su not in {"X", "Y", "Z"}:
            raise ConfigError(f"unknown suite: {s}")
        out.append(su if su != "mqtt_acl" else "mqtt_acl")
    return out


_SECRET_RE = re.compile(
    r"(?i)(password|token|authorization|bearer|secret|cookie)=([^\s&]+)"
)


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=<redacted>", text)
