#!/usr/bin/env python3
"""Disposable authenticated ZAP Automation Framework runner.

Soft-OPEN until a real disposable scan produces High=0 evidence.

Authenticated coverage is claimed only from scanner-origin evidence: ZAP's own
message history (AF ``export`` job, ``source: all``) must show the three
``requestor`` probes (before / during / after the scan jobs) to the auth-check
endpoint carrying the scanner credential and returning HTTP 200 JSON whose
``username`` equals ``OPENFDD_ZAP_EXPECTED_USERNAME``. The independent
preflight is a precondition only, never proof.

Evidence handling:
  * The raw ZAP JSON report is read once, hashed (SHA-256), and copied
    byte-for-byte into a write-once evidence directory. It is never rewritten.
  * The raw message-history HAR carries request headers (secret-bearing). It is
    hashed, parsed in memory, and deleted; only a redacted summary is kept.
  * Derived files (parsed alert instances, auth evidence) are separate files.

Modes:
  --selftest
      Validate af_plan.yaml hygiene + verdict schema; write BLOCKED verdict; exit 2.
  OPENFDD_ZAP_AF_EXECUTE=1 + ZAP_TARGET_ORIGIN + OPENFDD_ZAP_EXPECTED_USERNAME
  + (ZAP_AUTH_HEADER_FILE | ZAP_AUTH_HEADER_VALUE)
      Run AF passive (+ active when OPENFDD_ZAP_AF_ACTIVE=1) against the exact
      disposable origin and write the verdict.
  --negative-control
      Same, but the scanner is given a deliberately broken credential while
      the preflight uses the real one. Run auth probes only; exit 0 only when
      all three scanner-origin probes demonstrably receive JSON 401/403 denials.
      HTTP 200 is FAIL; missing, broken or unrelated evidence is ERROR.

Secrets are accepted only from env or a private (0600, caller-owned) file and
are passed to ZAP through the environment, never argv. Exit codes:
PASS 0, FAIL/ERROR 1, BLOCKED 2.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("ERROR: PyYAML required (pip/uv install pyyaml)") from e

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = Path(__file__).resolve().parent / "af_plan.yaml"
DISPOSITION_PATH = Path(__file__).resolve().parent / "medium_dispositions.json"
DEFAULT_VERDICT = ROOT / "reports" / "security" / "zap_af_verdict.json"
DEFAULT_NEGATIVE_VERDICT = ROOT / "reports" / "security" / "zap_af_negative_control_verdict.json"
# Qualification default is digest-pinned (A07). Override only with another digest.
_PINNED_ZAP_DIGEST = (
    "ghcr.io/zaproxy/zaproxy@sha256:"
    "781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef"
)
DEFAULT_ZAP_IMAGE = os.environ.get("OPENFDD_ZAP_IMAGE", _PINNED_ZAP_DIGEST)
CURL_IMAGE = "curlimages/curl:8.5.0"

SUITE = "zap_af_authenticated_v2"
NEGATIVE_SUITE = "zap_af_negative_control_v2"
CONTEXT_NAME = "openfdd-disposable"
SCANNER_USER = "openfdd-scanner"
AUTH_CHECK_PATH = "/api/auth/me"
PROBE_HEADER = "X-OpenFDD-Auth-Probe"
PROBE_PHASES = ("before", "during", "after")
REPORT_FILE = "zap-af-report.json"
MESSAGES_FILE = "zap-af-messages.har"
DISPOSITION_SCHEMA = "openfdd.zap_alert_disposition.v2"

DEFAULT_MAX_WALL_SECONDS = 5400
DEFAULT_MAX_REQUESTS = 60000
DISPOSABLE_DOCKER_ALIASES = frozenset({"web", "central"})
_DOCKER_NETWORK_RE = re.compile(r"^openfdd-zap-af-[A-Za-z0-9_.-]{1,64}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_PROXY_ENV = frozenset(
    k
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY")
    for k in (name, name.lower())
)
_SECRET_ENV = frozenset(
    {"ZAP_AUTH_HEADER_VALUE", "ZAP_AUTH_HEADER_FILE", "ZAP_AUTH_HEADER", "ZAP_AUTH_HEADER_SITE"}
)
_REQUIRED_PLACEHOLDERS = (
    "${ZAP_TARGET_ORIGIN}",
    "${ZAP_SCOPE_REGEX}",
    "${ZAP_PROBE_NONCE}",
    "${ZAP_LOGGED_IN_REGEX}",
    "${ZAP_REPORT_DIR}",
)

# Hardcoded JWT / Bearer material must never appear in the committed plan.
_HARDCODED_BEARER = re.compile(r"Bearer\s+(?!\$\{)[A-Za-z0-9\-_\.=]+", re.IGNORECASE)
_JWT_BLOB = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_REDACT_BEARER = re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}
)
_RISKS = {0: "Informational", 1: "Low", 2: "Medium", 3: "High"}


class EvidenceError(ValueError):
    """Scanner output does not match the strict expected schema."""


class ScopeError(ValueError):
    """Target origin, redirect, or proxy is outside the disposable scope."""


class ConfigError(ValueError):
    """Runner configuration (budgets, credential source, identity) is invalid."""


class Cancelled(RuntimeError):
    """SIGINT/SIGTERM received; owned processes were terminated."""


class BudgetExceeded(RuntimeError):
    """Total wall-clock budget exhausted."""


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #


def redact(text: str) -> str:
    """Strip bearer token material from any string before logging/artifacts."""
    text = _REDACT_BEARER.sub(r"\1<redacted>", text)
    return _JWT_BLOB.sub("<redacted-jwt>", text)


class SecretSet:
    """Exact secret values that must never reach argv, logs, or artifacts."""

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values: list[str] = []
        for v in values:
            self.add(v)

    def add(self, value: str | None) -> None:
        if not value or len(value) < 6:
            return
        candidates = {value}
        if value.lower().startswith("bearer "):
            candidates.add(value.split(" ", 1)[1].strip())
        for c in candidates:
            if len(c) >= 6 and c not in self._values:
                self._values.append(c)
        self._values.sort(key=len, reverse=True)

    def scrub(self, text: str) -> str:
        for v in self._values:
            text = text.replace(v, "<redacted-secret>")
        return redact(text)

    def found_in(self, data: bytes | str) -> bool:
        blob = data.encode("utf-8", errors="replace") if isinstance(data, str) else data
        return any(v.encode("utf-8") in blob for v in self._values)

    def sweep(self, roots: Iterable[Path]) -> list[str]:
        """Delete any file under ``roots`` that contains a secret; return their paths."""
        offending: list[str] = []
        for root in roots:
            if not root.exists():
                continue
            files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
            for p in files:
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                if self.found_in(data):
                    offending.append(p.name)
                    p.chmod(stat.S_IWUSR | stat.S_IRUSR)
                    p.unlink()
        return offending


def load_scanner_auth_header(env: dict[str, str] | None = None) -> str:
    """Return the scanner Authorization value from a private file or env.

    ``ZAP_AUTH_HEADER_FILE`` must be a regular file owned by the caller with
    no group/other permissions. Never logs the value.
    """
    env = os.environ if env is None else env
    file_path = (env.get("ZAP_AUTH_HEADER_FILE") or "").strip()
    if file_path:
        p = Path(file_path)
        try:
            st = p.lstat()
        except OSError as exc:
            raise ConfigError(f"ZAP_AUTH_HEADER_FILE unreadable ({type(exc).__name__})") from exc
        if not stat.S_ISREG(st.st_mode):
            raise ConfigError("ZAP_AUTH_HEADER_FILE must be a regular file (no symlinks)")
        if st.st_mode & 0o077:
            raise ConfigError("ZAP_AUTH_HEADER_FILE must not be group/other accessible (chmod 600)")
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise ConfigError("ZAP_AUTH_HEADER_FILE must be owned by the runner user")
        value = p.read_text(encoding="utf-8").strip()
    else:
        value = (env.get("ZAP_AUTH_HEADER_VALUE") or "").strip()
    if not value:
        raise ConfigError("scanner credential missing (ZAP_AUTH_HEADER_FILE or ZAP_AUTH_HEADER_VALUE)")
    if any(ch in value for ch in "\r\n\x00"):
        raise ConfigError("scanner credential contains control characters")
    if not value.lower().startswith("bearer ") or len(value.split(" ", 1)[1].strip()) < 8:
        raise ConfigError("scanner credential must be 'Bearer <token>'")
    return value


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Subprocess env without proxies or inherited scanner credentials."""
    env = {k: v for k, v in os.environ.items() if k not in _PROXY_ENV and k not in _SECRET_ENV}
    if extra:
        env.update(extra)
    return env


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TargetOrigin:
    scheme: str
    host: str
    port: int | None
    origin: str
    kind: str  # "loopback" | "docker_network"

    @property
    def scope_regex(self) -> str:
        return scope_regex(self.origin)

    @property
    def site_key(self) -> str:
        """host[:port] used for ZAP_AUTH_HEADER_SITE."""
        return self.origin.split("://", 1)[1]

    def url(self, path: str) -> str:
        return self.origin + path

    def in_scope(self, url: str) -> bool:
        return bool(re.fullmatch(self.scope_regex, url))


def scope_regex(origin: str) -> str:
    """Anchored, escaped include regex for exactly ``origin`` (no host suffixes)."""
    return "^" + re.escape(origin) + r"(?:[/?#].*)?$"


def parse_disposable_origin(raw: str, *, docker_network: str = "") -> TargetOrigin:
    """Accept only the exact canonical origin of a loopback or disposable host.

    Loopback (127.0.0.0/8, ::1, localhost) is always disposable. The docker
    aliases ``web`` / ``central`` are accepted only on a runner-owned
    ``openfdd-zap-af-*`` network. Anything else is refused before any
    credential is read.
    """
    raw = (raw or "").strip()
    if not raw or any(ch.isspace() for ch in raw) or "\\" in raw:
        raise ScopeError("target origin empty or contains whitespace/backslash")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ScopeError("target origin scheme must be http or https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ScopeError("target origin must not contain userinfo")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ScopeError("target origin must not contain a path, query, or fragment")
    host = (parts.hostname or "").lower()
    if not host:
        raise ScopeError("target origin has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise ScopeError("target origin port invalid") from exc
    default_port = 443 if scheme == "https" else 80
    host_fmt = f"[{host}]" if ":" in host else host
    canonical = f"{scheme}://{host_fmt}" + (f":{port}" if port and port != default_port else "")
    if raw.rstrip("/") != canonical:
        raise ScopeError(f"target origin must be canonical ({canonical})")

    kind = ""
    if host == "localhost":
        kind = "loopback"
    else:
        try:
            if ipaddress.ip_address(host).is_loopback:
                kind = "loopback"
        except ValueError:
            pass
    if not kind and host in DISPOSABLE_DOCKER_ALIASES:
        if docker_network and _DOCKER_NETWORK_RE.match(docker_network):
            kind = "docker_network"
        else:
            raise ScopeError(
                "docker alias target requires ZAP_DOCKER_NETWORK=openfdd-zap-af-* (runner-owned)"
            )
    if not kind:
        raise ScopeError("target host is not a loopback or disposable docker-network host")
    return TargetOrigin(scheme=scheme, host=host, port=port, origin=canonical, kind=kind)


class _NoRedirect:
    """urllib handler that refuses every redirect (scope may not be left)."""

    @staticmethod
    def build_opener():
        import urllib.request

        class _Handler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
                raise ScopeError(f"redirect refused (HTTP {code})")

        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Handler())


# --------------------------------------------------------------------------- #
# Process ownership + budgets
# --------------------------------------------------------------------------- #

_CANCEL = threading.Event()


@dataclass
class ProcResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    duration_s: float = 0.0


def _docker_rm_force(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=60,
            check=False,
            env=child_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _terminate_group(proc: subprocess.Popen, grace_s: float = 5.0) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=grace_s)
            return
        except subprocess.TimeoutExpired:
            continue


def run_owned_process(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout_s: float,
    cwd: str | None = None,
    container_name: str | None = None,
    stdin_bytes: bytes | None = None,
) -> ProcResult:
    """Run ``cmd`` in its own process group with a hard timeout and cancel.

    On timeout or cancel the whole group is SIGTERM'd then SIGKILL'd. When the
    command starts a named container, ``docker rm -f`` always runs afterwards
    (killing the docker CLI does not stop the container).
    """
    started = time.monotonic()
    deadline = started + max(0.0, timeout_s)
    timed_out = cancelled = False
    out = err = b""
    try:
        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=cwd,
                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return ProcResult(returncode=127, stdout="", stderr=f"spawn failed: {type(exc).__name__}")
        pending_input = stdin_bytes
        while True:
            try:
                o, e = proc.communicate(input=pending_input, timeout=0.2)
                out += o or b""
                err += e or b""
                break
            except subprocess.TimeoutExpired:
                pending_input = None
                if _CANCEL.is_set():
                    cancelled = True
                elif time.monotonic() >= deadline:
                    timed_out = True
                if timed_out or cancelled:
                    _terminate_group(proc)
                    try:
                        o, e = proc.communicate(timeout=5)
                        out += o or b""
                        err += e or b""
                    except (subprocess.TimeoutExpired, ValueError):
                        pass
                    break
        rc = proc.returncode
    finally:
        if container_name:
            _docker_rm_force(container_name)
    return ProcResult(
        returncode=None if (timed_out or cancelled) else rc,
        stdout=out.decode("utf-8", errors="replace"),
        stderr=err.decode("utf-8", errors="replace"),
        timed_out=timed_out,
        cancelled=cancelled,
        duration_s=time.monotonic() - started,
    )


@dataclass
class Budget:
    max_wall_seconds: int
    max_requests: int
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return self.max_wall_seconds - (time.monotonic() - self.started)

    def timeout(self, cap: float) -> float:
        if _CANCEL.is_set():
            raise Cancelled("cancelled")
        left = self.remaining()
        if left <= 0:
            raise BudgetExceeded("wall-clock budget exhausted")
        return min(cap, left)


def load_budget(env: dict[str, str] | None = None) -> Budget:
    env = os.environ if env is None else env

    def _int(name: str, default: int, lo: int, hi: int) -> int:
        raw = (env.get(name) or "").strip()
        if not raw:
            return default
        if not raw.isdigit() or not lo <= int(raw) <= hi:
            raise ConfigError(f"{name} must be an integer in [{lo}, {hi}]")
        return int(raw)

    return Budget(
        max_wall_seconds=_int("OPENFDD_ZAP_MAX_WALL_SECONDS", DEFAULT_MAX_WALL_SECONDS, 60, 86400),
        max_requests=_int("OPENFDD_ZAP_MAX_REQUESTS", DEFAULT_MAX_REQUESTS, 1, 10_000_000),
    )


# --------------------------------------------------------------------------- #
# Plan hygiene + materialization
# --------------------------------------------------------------------------- #


def _probe_jobs(jobs: list[Any]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {p: [] for p in PROBE_PHASES}
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict) or job.get("type") != "requestor":
            continue
        for req in job.get("requests") or []:
            headers = req.get("headers") if isinstance(req, dict) else None
            for h in headers or []:
                for phase in PROBE_PHASES:
                    if h == f"{PROBE_HEADER}:{phase}-${{ZAP_PROBE_NONCE}}":
                        found[phase].append(idx)
    return found


def validate_af_plan(path: Path) -> list[str]:
    """Return human-readable hygiene errors (empty ⇒ OK)."""
    if not path.is_file():
        return [f"missing plan: {path}"]
    raw = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if _HARDCODED_BEARER.search(raw):
        errors.append("plan contains hardcoded Bearer token")
    if _JWT_BLOB.search(raw):
        errors.append("plan contains JWT-like blob (never commit tokens)")
    if "${ZAP_AUTH_HEADER" in raw:
        errors.append("plan must not reference the scanner credential (system env var only)")
    for ph in _REQUIRED_PLACEHOLDERS:
        if ph not in raw:
            errors.append(f"plan must reference {ph}")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return errors + [f"invalid YAML: {e}"]
    if not isinstance(data, dict):
        return errors + ["plan root must be a mapping"]

    env = data.get("env") or {}
    if not isinstance(env, dict):
        return errors + ["env must be a mapping"]
    if "proxy" in env:
        errors.append("env.proxy is refused (no upstream proxies outside scope)")
    configs = env.get("configs") or {}
    if isinstance(configs, dict) and any("proxy" in str(k).lower() for k in configs):
        errors.append("env.configs must not configure proxies")
    params = env.get("parameters") or {}
    if params.get("failOnError") is not True:
        errors.append("env.parameters.failOnError must be true")
    if params.get("continueOnFailure") not in (False, None):
        errors.append("env.parameters.continueOnFailure must be false")
    if params.get("progressToStdout") is not True:
        errors.append("env.parameters.progressToStdout must be true (passive drain evidence)")
    if "maxDuration" in params:
        errors.append("omit env.parameters.maxDuration for pinned add-on compatibility; runner enforces wall time")

    contexts = env.get("contexts") or []
    if not isinstance(contexts, list) or len(contexts) != 1 or not isinstance(contexts[0], dict):
        errors.append("env.contexts must be exactly one mapping")
    else:
        ctx = contexts[0]
        if ctx.get("name") != CONTEXT_NAME:
            errors.append(f"context name must be {CONTEXT_NAME}")
        urls = ctx.get("urls") or []
        if not urls or any(not str(u).startswith("${ZAP_TARGET_ORIGIN}/") for u in urls):
            errors.append("context urls must be nonempty and under ${ZAP_TARGET_ORIGIN}/")
        if ctx.get("includePaths") != ["${ZAP_SCOPE_REGEX}"]:
            errors.append("context includePaths must be exactly ['${ZAP_SCOPE_REGEX}']")
        auth = ctx.get("authentication") or {}
        if auth.get("method") != "manual":
            errors.append("authentication.method must be manual (header env injection)")
        ver = auth.get("verification") or {}
        if ver.get("method") != "poll":
            errors.append("authentication.verification.method must be poll")
        if ver.get("pollUrl") != "${ZAP_TARGET_ORIGIN}" + AUTH_CHECK_PATH:
            errors.append("verification.pollUrl must be the auth-check endpoint")
        if ver.get("loggedInRegex") != "${ZAP_LOGGED_IN_REGEX}":
            errors.append("verification.loggedInRegex must be ${ZAP_LOGGED_IN_REGEX}")
        users = ctx.get("users") or []
        if not any(isinstance(u, dict) and u.get("name") == SCANNER_USER for u in users):
            errors.append(f"context users must include {SCANNER_USER}")
        if "sessionManagement" in ctx:
            errors.append("sessionManagement must be omitted (header comes from ZAP env vars)")

    jobs = data.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        return errors + ["jobs must be a nonempty list"]
    types = [j.get("type") if isinstance(j, dict) else None for j in jobs]
    for required in ("requestor", "openapi", "spider", "passiveScan-wait", "export", "report"):
        if required not in types:
            errors.append(f"jobs missing required type: {required}")
    if "activeScan" in types:
        errors.append("activeScan is inserted by the runner, not the template")
    for j in jobs:
        if not isinstance(j, dict):
            errors.append("every job must be a mapping")
            continue
        p = j.get("parameters") or {}
        if j.get("failOnError") is False or p.get("failOnError") is False:
            errors.append("failOnError=false must not swallow AF errors")
        if j.get("type") == "passiveScan-wait" and p.get("maxDuration", 0) != 0:
            errors.append("passiveScan-wait.maxDuration must be 0 (drain the queue)")
        if j.get("type") == "spider" and p.get("user") != SCANNER_USER:
            errors.append(f"spider must run as {SCANNER_USER}")
        if j.get("type") == "requestor":
            if p.get("user") != SCANNER_USER:
                errors.append(f"requestor must run as {SCANNER_USER}")
            for req in j.get("requests") or []:
                if req.get("url") != "${ZAP_TARGET_ORIGIN}" + AUTH_CHECK_PATH:
                    errors.append("requestor probes must target the auth-check endpoint only")
                if req.get("responseCode") != 200:
                    errors.append("requestor probes must expect responseCode 200")
        if j.get("type") in ("export", "report") and j.get("alwaysRun") is not True:
            errors.append(f"{j.get('type')} must set alwaysRun: true (evidence survives early exit)")
        if j.get("type") == "export":
            if p.get("type") != "har" or p.get("source") != "all":
                errors.append("export must be type=har source=all (scanner message history)")
            if not str(p.get("fileName") or "").endswith("/" + MESSAGES_FILE):
                errors.append(f"export fileName must end with {MESSAGES_FILE}")
        if j.get("type") == "report":
            if p.get("template") != "traditional-json" or p.get("reportFile") != "zap-af-report":
                errors.append("report must be traditional-json zap-af-report")

    probes = _probe_jobs(jobs)
    for phase in PROBE_PHASES:
        if len(probes[phase]) != 1:
            errors.append(f"plan must contain exactly one {phase} auth probe")
    if all(len(probes[p]) == 1 for p in PROBE_PHASES):
        b, d, a = (probes[p][0] for p in PROBE_PHASES)
        first = lambda t: types.index(t) if t in types else -1  # noqa: E731
        last = lambda t: len(types) - 1 - types[::-1].index(t) if t in types else -1  # noqa: E731
        if not (b < first("openapi") < d < first("spider") < a):
            errors.append("auth probes must run before / during / after the scan jobs")
        if not (a < last("passiveScan-wait") < first("export") < first("report")):
            errors.append("final passiveScan-wait → export → report must follow the after probe")
    return errors


def _substitute(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str):
        for k, v in values.items():
            node = node.replace(k, v)
        return node
    if isinstance(node, list):
        return [_substitute(x, values) for x in node]
    if isinstance(node, dict):
        return {k: _substitute(v, values) for k, v in node.items()}
    return node


def logged_in_regex(expected_username: str) -> str:
    return r'"username"\s*:\s*"' + re.escape(expected_username) + '"'


def materialize_plan(
    *,
    target: TargetOrigin,
    report_dir: str,
    active: bool,
    nonce: str,
    expected_username: str,
    max_seconds: int,
    dest: Path,
    secrets: SecretSet | None = None,
    negative_control: bool = False,
) -> dict[str, Any]:
    """Render the template into ``dest``; returns the rendered plan."""
    template = yaml.safe_load(PLAN_PATH.read_text(encoding="utf-8"))
    after_idx = _probe_jobs(template["jobs"])["after"][0]
    data = _substitute(
        template,
        {
            "${ZAP_TARGET_ORIGIN}": target.origin,
            "${ZAP_SCOPE_REGEX}": target.scope_regex,
            "${ZAP_PROBE_NONCE}": nonce,
            "${ZAP_LOGGED_IN_REGEX}": logged_in_regex(expected_username),
            "${ZAP_REPORT_DIR}": report_dir.rstrip("/"),
        },
    )
    jobs = list(data["jobs"])
    if negative_control:
        # A bad credential must not accidentally reach imported mutation routes.
        # Do not stop after the first expected denial, or evaluate positive-login
        # statistics. The dedicated evaluator accepts either HTTP 401 or 403.
        jobs = [j for j in jobs if j["type"] in ("requestor", "export", "report")]
        for job in jobs:
            if job["type"] == "requestor":
                job.pop("tests", None)
                for request in job["requests"]:
                    request.pop("responseCode", None)
        data["env"]["contexts"][0]["authentication"].pop("verification", None)
    elif active:
        active_jobs = [
            {
                "type": "activeScan",
                "parameters": {
                    "context": CONTEXT_NAME,
                    "user": SCANNER_USER,
                    "policy": "Default Policy",
                    "maxRuleDurationInMins": 5,
                    "maxScanDurationInMins": max(1, min(30, int(max_seconds) // 60)),
                },
            },
            {"type": "passiveScan-wait", "parameters": {"maxDuration": 0}},
        ]
        jobs = jobs[:after_idx] + active_jobs + jobs[after_idx:]
    data["jobs"] = jobs
    text = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    if _HARDCODED_BEARER.search(text) or _JWT_BLOB.search(text):
        raise SystemExit("ERROR: rendered plan leaked auth material")
    if secrets is not None and secrets.found_in(text):
        raise SystemExit("ERROR: rendered plan leaked the scanner credential")
    if "${" in text:
        raise SystemExit("ERROR: rendered plan has unresolved placeholders")
    dest.write_text(text, encoding="utf-8")
    return data


def expected_passive_waits(plan: dict[str, Any]) -> int:
    return sum(1 for j in plan.get("jobs") or [] if j.get("type") == "passiveScan-wait")


def passive_drain_errors(stdout: str, expected: int) -> list[str]:
    """AF progress must show every passiveScan-wait job finished (queue drained)."""
    started = len(re.findall(r"Job passiveScan-wait started", stdout))
    finished = len(re.findall(r"Job passiveScan-wait finished", stdout))
    if expected <= 0:
        return ["plan has no passiveScan-wait job"]
    if started < expected or finished < expected:
        return [
            "passive scan queue not confirmed drained "
            f"(passiveScan-wait started={started} finished={finished} expected={expected})"
        ]
    return []


# --------------------------------------------------------------------------- #
# Strict scanner output parsing
# --------------------------------------------------------------------------- #

_REPORT_ROOT_REQUIRED = {"@programName", "@version", "site"}
_REPORT_ROOT_OPTIONAL = {
    "@generated",
    "created",
    "insights",
    "stoppingInsight",
    "scriptDiagnostics",
    "sequences",
}
_SITE_KEYS = {"@name", "@host", "@port", "@ssl", "alerts"}
_ALERT_REQUIRED = {"pluginid", "alert", "riskcode", "confidence", "riskdesc", "instances", "count"}
_ALERT_OPTIONAL = {
    "alertRef",
    "name",
    "desc",
    "systemic",
    "solution",
    "otherinfo",
    "reference",
    "cweid",
    "wascid",
    "sourceid",
}
_INSTANCE_REQUIRED = {"uri", "method", "param", "attack", "evidence"}
_INSTANCE_OPTIONAL = {"id", "nodeName", "otherinfo"}


def _check_keys(obj: Any, where: str, required: set[str], optional: set[str]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise EvidenceError(f"{where} must be an object")
    missing = sorted(required - obj.keys())
    unknown = sorted(obj.keys() - required - optional)
    if missing:
        raise EvidenceError(f"{where} missing fields {missing}")
    if unknown:
        raise EvidenceError(f"{where} has unknown fields {unknown}")
    return obj


def _str(obj: dict[str, Any], key: str, where: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str):
        raise EvidenceError(f"{where}.{key} must be a string")
    return val


def evidence_sha256(evidence: str) -> str:
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()


def route_of(url: str, target: TargetOrigin) -> str:
    rest = url[len(target.origin):]
    rest = rest.split("#", 1)[0]
    return rest if rest.startswith("/") else "/" + rest


@dataclass(frozen=True)
class AlertInstance:
    plugin_id: str
    alert_ref: str
    name: str
    risk: str
    confidence: int
    method: str
    url: str
    route: str
    param: str
    evidence_sha256: str

    def key(self) -> tuple[str, str, str, str, str]:
        return (self.plugin_id, self.method, self.route, self.param, self.evidence_sha256)

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "alert_ref": self.alert_ref,
            "alert_name": self.name,
            "risk": self.risk,
            "confidence": self.confidence,
            "method": self.method,
            "route": self.route,
            "param": self.param,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass
class ParsedReport:
    program: str
    version: str
    site_names: list[str]
    instances: list[AlertInstance]
    stopping_insight: bool

    def by_risk(self) -> dict[str, int]:
        out = {r: 0 for r in _RISKS.values()}
        for i in self.instances:
            out[i.risk] += 1
        return out


def parse_traditional_report(data: Any, target: TargetOrigin) -> ParsedReport:
    """Strict traditional-json parse. Any malformed or unknown field raises."""
    root = _check_keys(data, "report", _REPORT_ROOT_REQUIRED, _REPORT_ROOT_OPTIONAL)
    program = _str(root, "@programName", "report")
    version = _str(root, "@version", "report")
    if program != "ZAP":
        raise EvidenceError("report @programName must be ZAP")
    for key in ("insights", "sequences"):
        if key in root and not isinstance(root[key], list):
            raise EvidenceError(f"report.{key} must be a list")
    for key in ("stoppingInsight", "scriptDiagnostics"):
        if key in root and not isinstance(root[key], dict):
            raise EvidenceError(f"report.{key} must be an object")
    sites = root["site"]
    if not isinstance(sites, list) or not sites:
        raise EvidenceError("report.site must be a nonempty list")
    site_names: list[str] = []
    instances: list[AlertInstance] = []
    for s_idx, site in enumerate(sites):
        where = f"site[{s_idx}]"
        _check_keys(site, where, _SITE_KEYS, set())
        name = _str(site, "@name", where)
        for k in ("@host", "@port", "@ssl"):
            _str(site, k, where)
        if name.rstrip("/") != target.origin:
            raise EvidenceError(f"{where} does not match the configured target origin")
        site_names.append(name)
        alerts = site["alerts"]
        if not isinstance(alerts, list):
            raise EvidenceError(f"{where}.alerts must be a list")
        for a_idx, alert in enumerate(alerts):
            aw = f"{where}.alerts[{a_idx}]"
            _check_keys(alert, aw, _ALERT_REQUIRED, _ALERT_OPTIONAL)
            for k in (_ALERT_REQUIRED | _ALERT_OPTIONAL) - {"instances", "systemic"}:
                if k in alert:
                    _str(alert, k, aw)
            if "systemic" in alert and not isinstance(alert["systemic"], bool):
                raise EvidenceError(f"{aw}.systemic must be a boolean")
            plugin_id = alert["pluginid"]
            if not plugin_id.isdigit():
                raise EvidenceError(f"{aw}.pluginid must be numeric")
            if not alert["riskcode"].isdigit() or int(alert["riskcode"]) not in _RISKS:
                raise EvidenceError(f"{aw}.riskcode must be 0-3")
            risk = _RISKS[int(alert["riskcode"])]
            if alert["riskdesc"].split(" ", 1)[0] != risk:
                raise EvidenceError(f"{aw}.riskdesc disagrees with riskcode")
            if not alert["confidence"].isdigit() or not 0 <= int(alert["confidence"]) <= 4:
                raise EvidenceError(f"{aw}.confidence must be 0-4")
            alert_ref = alert.get("alertRef", plugin_id)
            if alert_ref != plugin_id and not alert_ref.startswith(plugin_id + "-"):
                raise EvidenceError(f"{aw}.alertRef does not belong to pluginid")
            name_ = alert["alert"].strip()
            if not name_ or ("name" in alert and alert["name"].strip() != name_):
                raise EvidenceError(f"{aw}.alert/name must be nonempty and agree")
            raw_instances = alert["instances"]
            if not isinstance(raw_instances, list) or not raw_instances:
                raise EvidenceError(f"{aw}.instances must be a nonempty list")
            if not alert["count"].isdigit() or int(alert["count"]) != len(raw_instances):
                raise EvidenceError(f"{aw}.count disagrees with instances")
            for i_idx, inst in enumerate(raw_instances):
                iw = f"{aw}.instances[{i_idx}]"
                _check_keys(inst, iw, _INSTANCE_REQUIRED, _INSTANCE_OPTIONAL)
                for k in _INSTANCE_REQUIRED | {"id", "otherinfo"}:
                    if k in inst:
                        _str(inst, k, iw)
                if "nodeName" in inst and not isinstance(inst["nodeName"], (str, type(None))):
                    raise EvidenceError(f"{iw}.nodeName must be a string or null")
                uri = inst["uri"]
                if not target.in_scope(uri):
                    raise EvidenceError(f"{iw}.uri is outside the target scope")
                method = inst["method"].upper()
                if method not in _HTTP_METHODS:
                    raise EvidenceError(f"{iw}.method is not an HTTP method")
                instances.append(
                    AlertInstance(
                        plugin_id=plugin_id,
                        alert_ref=alert_ref,
                        name=name_,
                        risk=risk,
                        confidence=int(alert["confidence"]),
                        method=method,
                        url=uri,
                        route=route_of(uri, target),
                        param=inst["param"],
                        evidence_sha256=evidence_sha256(inst["evidence"]),
                    )
                )
    return ParsedReport(
        program=program,
        version=version,
        site_names=site_names,
        instances=instances,
        stopping_insight="stoppingInsight" in root,
    )


# --------------------------------------------------------------------------- #
# Per-instance dispositions
# --------------------------------------------------------------------------- #

_DISP_REQUIRED = {
    "id",
    "plugin_id",
    "method",
    "route",
    "param",
    "evidence_sha256",
    "alert_name",
    "component",
    "owner",
    "rationale",
    "expiry",
    "retest",
    "candidate_binding",
}
_DISP_OPTIONAL = {"host_scope"}
_PENDING_REQUIRED = {"plugin_id", "alert_name", "owner", "rationale"}
_PENDING_OPTIONAL = {"component", "host_scope", "retest", "candidate_binding", "expiry"}


@dataclass(frozen=True)
class Disposition:
    id: str
    plugin_id: str
    method: str
    route: str
    param: str
    evidence_sha256: str
    alert_name: str
    expiry: str

    def key(self) -> tuple[str, str, str, str, str]:
        return (self.plugin_id, self.method, self.route, self.param, self.evidence_sha256)


def load_dispositions(
    path: Path | None = None, *, today: str | None = None
) -> list[Disposition]:
    """Strict per-instance disposition loader. Raises EvidenceError on any defect."""
    p = path or DISPOSITION_PATH
    day = today or date.today().isoformat()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"dispositions unreadable: {type(exc).__name__}") from exc
    _check_keys(raw, "dispositions", {"schema_version", "dispositions"}, {"pending_rebind"})
    if raw["schema_version"] != DISPOSITION_SCHEMA:
        raise EvidenceError(f"dispositions schema_version must be {DISPOSITION_SCHEMA}")
    if not isinstance(raw["dispositions"], list):
        raise EvidenceError("dispositions.dispositions must be a list")
    for idx, item in enumerate(raw.get("pending_rebind") or []):
        _check_keys(item, f"pending_rebind[{idx}]", _PENDING_REQUIRED, _PENDING_OPTIONAL)
    out: list[Disposition] = []
    ids: set[str] = set()
    keys: set[tuple[str, ...]] = set()
    for idx, item in enumerate(raw["dispositions"]):
        where = f"dispositions[{idx}]"
        _check_keys(item, where, _DISP_REQUIRED, _DISP_OPTIONAL)
        for k in _DISP_REQUIRED | (_DISP_OPTIONAL & item.keys()):
            if not isinstance(item[k], str) or (k != "param" and not item[k].strip()):
                raise EvidenceError(f"{where}.{k} must be a nonempty string")
        if not item["plugin_id"].isdigit():
            raise EvidenceError(f"{where}.plugin_id must be numeric")
        if item["method"] not in _HTTP_METHODS:
            raise EvidenceError(f"{where}.method must be an uppercase HTTP method")
        if not item["route"].startswith("/"):
            raise EvidenceError(f"{where}.route must start with /")
        if not _SHA256_RE.match(item["evidence_sha256"]):
            raise EvidenceError(f"{where}.evidence_sha256 must be 64 lowercase hex")
        exp = item["expiry"]
        if not _ISO_DAY_RE.match(exp):
            raise EvidenceError(f"{where}.expiry not YYYY-MM-DD: {exp!r}")
        try:
            datetime.strptime(exp, "%Y-%m-%d")
        except ValueError as exc:
            raise EvidenceError(f"{where}.expiry invalid calendar date: {exp}") from exc
        if exp < day:
            raise EvidenceError(f"{where} ({item['id']}) expired {exp}")
        d = Disposition(
            id=item["id"],
            plugin_id=item["plugin_id"],
            method=item["method"],
            route=item["route"],
            param=item["param"],
            evidence_sha256=item["evidence_sha256"],
            alert_name=item["alert_name"],
            expiry=exp,
        )
        if d.id in ids:
            raise EvidenceError(f"duplicate disposition id={d.id}")
        if d.key() in keys:
            raise EvidenceError(f"duplicate disposition instance key (id={d.id})")
        ids.add(d.id)
        keys.add(d.key())
        out.append(d)
    return out


def apply_dispositions(
    instances: list[AlertInstance], dispositions: list[Disposition]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (accepted, unaccepted) Medium instances. Matching is exact per instance."""
    by_key = {d.key(): d for d in dispositions}
    accepted: list[dict[str, Any]] = []
    unaccepted: list[dict[str, Any]] = []
    for inst in instances:
        if inst.risk != "Medium":
            continue
        d = by_key.get(inst.key())
        row = inst.as_dict()
        if d is None:
            row["reason"] = "no disposition for this instance"
            unaccepted.append(row)
        elif d.alert_name != inst.name:
            row["reason"] = f"disposition {d.id} alert_name mismatch"
            unaccepted.append(row)
        else:
            row["disposition_id"] = d.id
            row["expiry"] = d.expiry
            accepted.append(row)
    return accepted, unaccepted


# --------------------------------------------------------------------------- #
# Scanner-origin authentication evidence (ZAP message history HAR)
# --------------------------------------------------------------------------- #

_HAR_ENTRY_KEYS = {
    "pageref",
    "startedDateTime",
    "time",
    "request",
    "response",
    "cache",
    "timings",
    "serverIPAddress",
    "connection",
    "comment",
}
_HAR_REQUEST_KEYS = {
    "method",
    "url",
    "httpVersion",
    "cookies",
    "headers",
    "queryString",
    "postData",
    "headersSize",
    "bodySize",
    "comment",
}
_HAR_RESPONSE_KEYS = {
    "status",
    "statusText",
    "httpVersion",
    "cookies",
    "headers",
    "content",
    "redirectURL",
    "headersSize",
    "bodySize",
    "comment",
}
_HAR_CONTENT_KEYS = {"size", "compression", "mimeType", "text", "encoding", "comment"}


def _har_keys(obj: Any, where: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise EvidenceError(f"{where} must be an object")
    unknown = sorted(k for k in obj if k not in allowed and not k.startswith("_"))
    if unknown:
        raise EvidenceError(f"{where} has unknown fields {unknown}")
    missing = sorted(required - obj.keys())
    if missing:
        raise EvidenceError(f"{where} missing fields {missing}")
    return obj


def _har_headers(raw: Any, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        raise EvidenceError(f"{where} must be a list")
    out = []
    for i, h in enumerate(raw):
        _har_keys(h, f"{where}[{i}]", {"name", "value", "comment"}, {"name", "value"})
        if not isinstance(h["name"], str) or not isinstance(h["value"], str):
            raise EvidenceError(f"{where}[{i}] name/value must be strings")
        out.append((h["name"].lower(), h["value"]))
    return tuple(out)


@dataclass(frozen=True)
class HarEntry:
    index: int
    method: str
    url: str
    request_headers: tuple[tuple[str, str], ...]
    status: int
    response_headers: tuple[tuple[str, str], ...]
    mime_type: str
    body: bytes
    redirect_url: str

    def req_header(self, name: str) -> list[str]:
        n = name.lower()
        return [v for k, v in self.request_headers if k == n]

    def resp_header(self, name: str) -> list[str]:
        n = name.lower()
        return [v for k, v in self.response_headers if k == n]


def parse_scanner_messages(raw: bytes) -> list[HarEntry]:
    """Strictly parse the ZAP-exported HAR (message history)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"scanner message history is not JSON ({type(exc).__name__})") from exc
    root = _har_keys(data, "har", {"log"}, {"log"})
    log = _har_keys(
        root["log"], "har.log", {"version", "creator", "browser", "pages", "entries", "comment"},
        {"entries"},
    )
    entries = log["entries"]
    if not isinstance(entries, list):
        raise EvidenceError("har.log.entries must be a list")
    out: list[HarEntry] = []
    for idx, e in enumerate(entries):
        where = f"har.entries[{idx}]"
        _har_keys(e, where, _HAR_ENTRY_KEYS, {"request", "response"})
        req = _har_keys(e["request"], f"{where}.request", _HAR_REQUEST_KEYS, {"method", "url", "headers"})
        resp = _har_keys(e["response"], f"{where}.response", _HAR_RESPONSE_KEYS, {"status", "headers"})
        if not isinstance(req["method"], str) or not isinstance(req["url"], str):
            raise EvidenceError(f"{where}.request method/url must be strings")
        if not isinstance(resp["status"], int) or isinstance(resp["status"], bool):
            raise EvidenceError(f"{where}.response.status must be an integer")
        content = resp.get("content") or {}
        _har_keys(content, f"{where}.response.content", _HAR_CONTENT_KEYS, set())
        text = content.get("text")
        body = b""
        if text is not None:
            if not isinstance(text, str):
                raise EvidenceError(f"{where}.response.content.text must be a string")
            if content.get("encoding") == "base64":
                try:
                    body = base64.b64decode(text, validate=True)
                except ValueError as exc:
                    raise EvidenceError(f"{where}.response.content base64 invalid") from exc
            elif content.get("encoding") in (None, ""):
                body = text.encode("utf-8")
            else:
                raise EvidenceError(f"{where}.response.content.encoding unsupported")
        redirect = resp.get("redirectURL") or ""
        if not isinstance(redirect, str):
            raise EvidenceError(f"{where}.response.redirectURL must be a string")
        out.append(
            HarEntry(
                index=idx,
                method=req["method"].upper(),
                url=req["url"],
                request_headers=_har_headers(req["headers"], f"{where}.request.headers"),
                status=resp["status"],
                response_headers=_har_headers(resp["headers"], f"{where}.response.headers"),
                mime_type=str(content.get("mimeType") or ""),
                body=body,
                redirect_url=redirect,
            )
        )
    return out


def verify_auth_me_response(
    *,
    status: int,
    body: bytes,
    content_type: str = "",
    expected_username: str | None = None,
) -> dict[str, Any]:
    """Require HTTP 200 + JSON identity (ok=true, username, role).

    When ``expected_username`` is given the username must match exactly.
    Never returns the body.
    """
    result: dict[str, Any] = {
        "ok": False,
        "status": int(status),
        "path": AUTH_CHECK_PATH,
        "schema_ok": False,
        "identity_match": False,
    }
    if status != 200:
        result["error"] = "non_200"
        return result
    if "json" not in (content_type or "").lower():
        result["error"] = "non_json_content_type"
        return result
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result["error"] = "non_json"
        return result
    if not isinstance(data, dict) or not data:
        result["error"] = "empty_or_non_object"
        return result
    username = data.get("username")
    role = data.get("role")
    if data.get("ok") is not True or not isinstance(username, str) or not username.strip():
        result["error"] = "missing_identity"
        return result
    if not isinstance(role, str) or not role.strip():
        result["error"] = "missing_role"
        return result
    result["schema_ok"] = True
    if expected_username is not None and not hmac.compare_digest(username, expected_username):
        result["error"] = "identity_mismatch"
        return result
    result["identity_match"] = expected_username is not None
    result["ok"] = True
    result["role"] = role
    return result


def evaluate_scanner_auth(
    entries: list[HarEntry],
    *,
    target: TargetOrigin,
    nonce: str,
    expected_auth_header: str,
    expected_username: str,
    max_requests: int,
) -> dict[str, Any]:
    """Scanner-origin auth proof + scope/redirect/request-budget checks.

    Returns a redacted evidence dict; ``ok`` is True only when every check holds.
    """
    errors: list[str] = []
    auth_url = target.url(AUTH_CHECK_PATH)
    out_of_scope = [e for e in entries if not target.in_scope(e.url)]
    leaked = [e for e in out_of_scope if e.req_header("authorization")]
    bad_redirects = []
    for e in entries:
        if 300 <= e.status < 400:
            locs = e.resp_header("location") + ([e.redirect_url] if e.redirect_url else [])
            if any(not target.in_scope(urljoin(e.url, loc)) for loc in locs):
                bad_redirects.append(e)
    if len(entries) > max_requests:
        errors.append(f"request budget exceeded ({len(entries)} > {max_requests})")
    if out_of_scope:
        errors.append(f"{len(out_of_scope)} scanner request(s) outside the target scope")
    if leaked:
        errors.append(f"{len(leaked)} out-of-scope request(s) carried an Authorization header")
    if bad_redirects:
        errors.append(f"{len(bad_redirects)} redirect(s) pointing outside the target scope")

    probes: dict[str, dict[str, Any]] = {}
    probe_index: dict[str, int] = {}
    probe_ids = {f"{p}-{nonce}" for p in PROBE_PHASES}
    stale_probes = 0
    for phase in PROBE_PHASES:
        tag = f"{phase}-{nonce}"
        hits = [
            e
            for e in entries
            if e.method == "GET" and e.url == auth_url and tag in e.req_header(PROBE_HEADER)
        ]
        info: dict[str, Any] = {"found": bool(hits)}
        if not hits:
            errors.append(f"no scanner-origin {phase} probe in ZAP message history")
            probes[phase] = info
            continue
        if len(hits) != 1 or hits[0].req_header(PROBE_HEADER) != [tag]:
            errors.append(f"{phase} probe must occur exactly once with one nonce header")
        hit = hits[0]
        probe_index[phase] = hit.index
        auth_values = hit.req_header("authorization")
        matches = len(auth_values) == 1 and hmac.compare_digest(
            auth_values[0].encode("utf-8"), expected_auth_header.encode("utf-8")
        )
        ctype = hit.mime_type or ", ".join(hit.resp_header("content-type"))
        ident = verify_auth_me_response(
            status=hit.status,
            body=hit.body,
            content_type=ctype,
            expected_username=expected_username,
        )
        info.update(
            {
                "index": hit.index,
                "authorization_present": bool(auth_values),
                "authorization_matches": matches,
                "status": hit.status,
                "identity_ok": bool(ident.get("ok")),
                "identity_error": ident.get("error"),
            }
        )
        if not matches:
            errors.append(f"{phase} probe did not carry the scanner credential")
        if not ident.get("ok"):
            errors.append(f"{phase} probe identity check failed ({ident.get('error')})")
        probes[phase] = info
    for e in entries:
        tags = e.req_header(PROBE_HEADER)
        if tags and not any(t in probe_ids for t in tags):
            stale_probes += 1
    if stale_probes:
        errors.append(f"{stale_probes} stale or unknown probe nonce(s)")

    scan_entries = [e for e in entries if not e.req_header(PROBE_HEADER)]
    if len(probe_index) == len(PROBE_PHASES):
        b, d, a = (probe_index[p] for p in PROBE_PHASES)
        if not b < d < a:
            errors.append("auth probes out of order (before < during < after required)")
        elif not any(b < e.index < d for e in scan_entries) or not any(
            d < e.index < a for e in scan_entries
        ):
            errors.append("auth probes do not bracket scanner traffic (before/during/after)")
    in_scope_scan = [e for e in scan_entries if target.in_scope(e.url)]
    authorized = sum(
        1
        for e in in_scope_scan
        if any(
            hmac.compare_digest(v.encode("utf-8"), expected_auth_header.encode("utf-8"))
            for v in e.req_header("authorization")
        )
    )
    return {
        "ok": not errors,
        "errors": errors,
        "source": "zap_message_history_har",
        "request_count": len(entries),
        "max_requests": max_requests,
        "out_of_scope_count": len(out_of_scope),
        "out_of_scope_with_authorization": len(leaked),
        "redirects_out_of_scope": len(bad_redirects),
        "stale_probe_count": stale_probes,
        "probes": probes,
        "in_scope_scan_requests": len(in_scope_scan),
        "in_scope_scan_requests_with_credential": authorized,
    }


def evaluate_negative_control(
    entries: list[HarEntry],
    *,
    target: TargetOrigin,
    nonce: str,
    scanner_auth_header: str,
    max_requests: int,
) -> dict[str, Any]:
    """Require actual denials of the injected bad credential, never invert auth.

    A transport failure, missing header, wrong nonce, redirect or HTTP 500 cannot
    establish credential rejection. The negative plan deliberately sends only
    these three probes, so unexpected scanner traffic invalidates its evidence.
    """
    errors: list[str] = []
    probes: dict[str, dict[str, Any]] = {}
    indices: list[int] = []
    unexpected_success_count = 0
    if len(entries) > max_requests:
        errors.append(f"request budget exceeded ({len(entries)} > {max_requests})")
    out_of_scope = [e for e in entries if not target.in_scope(e.url)]
    if out_of_scope:
        errors.append(f"{len(out_of_scope)} scanner request(s) outside the target scope")
    for entry in entries:
        locations = entry.resp_header("location") + ([entry.redirect_url] if entry.redirect_url else [])
        if 300 <= entry.status < 400 and any(
            not target.in_scope(urljoin(entry.url, location)) for location in locations
        ):
            errors.append("scanner redirect points outside the target scope")
    known_tags = {f"{phase}-{nonce}" for phase in PROBE_PHASES}
    unexpected = [
        e for e in entries
        if e.method != "GET" or e.url != target.url(AUTH_CHECK_PATH)
        or len(e.req_header(PROBE_HEADER)) != 1
        or e.req_header(PROBE_HEADER)[0] not in known_tags
    ]
    if unexpected:
        errors.append(f"{len(unexpected)} unexpected request(s) or stale probe nonce(s)")
    for phase in PROBE_PHASES:
        tag = f"{phase}-{nonce}"
        hits = [
            e for e in entries
            if e.method == "GET" and e.url == target.url(AUTH_CHECK_PATH)
            and e.req_header(PROBE_HEADER) == [tag]
        ]
        info: dict[str, Any] = {"found": bool(hits), "count": len(hits)}
        probes[phase] = info
        unexpected_success_count += sum(hit.status == 200 for hit in hits)
        if len(hits) != 1:
            errors.append(f"{phase} probe must occur exactly once with the current nonce")
            continue
        hit = hits[0]
        indices.append(hit.index)
        headers = hit.req_header("authorization")
        matches = len(headers) == 1 and hmac.compare_digest(
            headers[0].encode("utf-8"), scanner_auth_header.encode("utf-8")
        )
        ctype = hit.mime_type or ", ".join(hit.resp_header("content-type"))
        denial_json = False
        if "json" in ctype.lower():
            try:
                body = json.loads(hit.body.decode("utf-8"))
                denial_json = isinstance(body, dict) and body.get("ok") is False
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        info.update(index=hit.index, authorization_matches=matches, status=hit.status,
                    denial_json=denial_json, denied=hit.status in (401, 403) and denial_json)
        if not matches:
            errors.append(f"{phase} probe did not carry the injected bad credential")
        if hit.status not in (401, 403) or not denial_json:
            errors.append(f"{phase} probe is not a JSON 401/403 denial")
    if len(indices) == len(PROBE_PHASES) and indices != sorted(set(indices)):
        errors.append("negative control probes out of order")
    return {
        "ok": not errors,
        "errors": errors,
        "source": "zap_message_history_har",
        "contract": "bad_credential_json_denial_before_during_after_v2",
        "request_count": len(entries),
        "max_requests": max_requests,
        "out_of_scope_count": len(out_of_scope),
        "unexpected_request_count": len(unexpected),
        "unexpected_success_count": unexpected_success_count,
        "probes": probes,
    }


# --------------------------------------------------------------------------- #
# Verdicts + write-once evidence
# --------------------------------------------------------------------------- #


def verdict_schema_ok(verdict: dict[str, Any]) -> list[str]:
    """Validate verdict object shape; also reject embedded secrets."""
    errors: list[str] = []
    required = (
        "suite",
        "status",
        "mode",
        "plan_hygiene_ok",
        "high_alerts",
        "medium_alerts",
        "zap_available",
        "active_scan",
        "notes",
    )
    for k in required:
        if k not in verdict:
            errors.append(f"verdict missing key: {k}")
    if verdict.get("status") not in ("PASS", "FAIL", "BLOCKED", "ERROR"):
        errors.append(f"invalid status: {verdict.get('status')!r}")
    for key in ("high_alerts", "medium_alerts"):
        value = verdict.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            errors.append(f"{key} must be a nonnegative integer or null when not evaluated")
    if verdict.get("status") == "PASS" and verdict.get("mode") == "execute":
        if verdict.get("alert_counts_evaluated") is not True:
            errors.append("scan PASS requires evaluated alert counts")
        if any(verdict.get(key) is None for key in ("high_alerts", "medium_alerts")):
            errors.append("scan PASS requires known alert counts")
    blob = json.dumps(verdict)
    if _JWT_BLOB.search(blob) or _HARDCODED_BEARER.search(blob):
        errors.append("verdict must not embed JWT / Bearer tokens")
    return errors


def write_verdict(path: Path, verdict: dict[str, Any]) -> None:
    errs = verdict_schema_ok(verdict)
    if errs:
        raise SystemExit("ERROR: refusing to write invalid verdict: " + "; ".join(errs))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def build_verdict(*, secrets: SecretSet | None = None, suite: str = SUITE, **kwargs: Any) -> dict[str, Any]:
    base = {
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": _rel(PLAN_PATH),
        "artifact_policy": "no_secret_in_verdict_logs_or_artifacts",
    }
    base.update(kwargs)
    scrub = secrets.scrub if secrets is not None else redact
    return _scrub_tree(json.loads(json.dumps(base)), scrub)


def _scrub_tree(node: Any, scrub: Any) -> Any:
    if isinstance(node, str):
        return scrub(node)
    if isinstance(node, list):
        return [_scrub_tree(x, scrub) for x in node]
    if isinstance(node, dict):
        return {k: _scrub_tree(v, scrub) for k, v in node.items()}
    return node


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_once(path: Path, data: bytes) -> str:
    """Create ``path`` exclusively, make it read-only, and return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as fh:
        fh.write(data)
    path.chmod(stat.S_IRUSR | stat.S_IRGRP)
    digest = sha256_bytes(path.read_bytes())
    if digest != sha256_bytes(data):
        raise EvidenceError(f"write-once verification failed for {path.name}")
    return digest


def zap_image_is_digest_pinned(image: str) -> bool:
    return "@sha256:" in (image or "")


def detect_zap() -> tuple[str | None, str]:
    """Return (mode, detail) where mode is 'zap.sh' | 'docker' | None."""
    zap_sh = shutil.which("zap.sh")
    if zap_sh:
        return "zap.sh", zap_sh
    if shutil.which("docker"):
        res = run_owned_process(["docker", "info"], env=child_env(), timeout_s=30)
        if res.returncode != 0:
            return None, "docker present but daemon unavailable"
        return "docker", DEFAULT_ZAP_IMAGE
    return None, "neither zap.sh nor docker available"


# --------------------------------------------------------------------------- #
# Network helpers (preflight + OpenAPI staging), scope-locked
# --------------------------------------------------------------------------- #


def _curl_config_header(auth_header: str) -> bytes:
    escaped = auth_header.replace("\\", "\\\\").replace('"', '\\"')
    return f'header = "Authorization: {escaped}"\n'.encode("utf-8")


def _parse_curl_dump(raw: bytes) -> tuple[int, str, bytes]:
    sep = raw.find(b"\r\n\r\n")
    sep_len = 4
    if sep < 0:
        sep, sep_len = raw.find(b"\n\n"), 2
    if sep < 0:
        return 0, "", b""
    header_blob = raw[:sep].decode("utf-8", errors="replace")
    body = raw[sep + sep_len:]
    status, ctype = 0, ""
    for line in header_blob.splitlines():
        if line.upper().startswith("HTTP/"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
        elif line.lower().startswith("content-type:"):
            ctype = line.split(":", 1)[1].strip()
    return status, ctype, body


def fetch_auth_me_preflight(
    *,
    target: TargetOrigin,
    auth_header: str,
    expected_username: str,
    budget: Budget,
    docker_network: str = "",
) -> dict[str, Any]:
    """Independent GET /api/auth/me (precondition only, never scanner proof).

    No proxies, no redirects. On a docker network the credential is handed to
    curl through ``--config -`` on stdin, never argv.
    """
    me_url = target.url(AUTH_CHECK_PATH)
    if target.kind == "docker_network":
        name = f"openfdd-zap-preflight-{uuid.uuid4().hex[:12]}"
        res = run_owned_process(
            [
                "docker", "run", "--rm", "-i", "--name", name,
                "--label", "openfdd.zap.owner=run_af_disposable",
                "--network", docker_network, CURL_IMAGE,
                "-sS", "--max-time", "20", "--max-redirs", "0", "--noproxy", "*",
                "--proto", "=http,https", "-K", "-",
                "-D", "-", "-o", "-", "-H", "Accept: application/json", me_url,
            ],
            env=child_env(),
            timeout_s=budget.timeout(60),
            container_name=name,
            stdin_bytes=_curl_config_header(auth_header),
        )
        if res.timed_out or res.cancelled:
            return {"ok": False, "path": AUTH_CHECK_PATH, "error": "preflight_timeout", "via": "docker_network"}
        status, ctype, body = _parse_curl_dump(res.stdout.encode("utf-8"))
        result = verify_auth_me_response(
            status=status, body=body, content_type=ctype, expected_username=expected_username
        )
        if 300 <= status < 400:
            result["error"] = "redirect_refused"
        result["via"] = "docker_network"
        return result

    import urllib.error
    import urllib.request

    opener = _NoRedirect.build_opener()
    req = urllib.request.Request(
        me_url, method="GET", headers={"Authorization": auth_header, "Accept": "application/json"}
    )
    try:
        with opener.open(req, timeout=budget.timeout(15)) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode())
            body = resp.read(1_048_576)
            ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
    except ScopeError:
        return {"ok": False, "path": AUTH_CHECK_PATH, "error": "redirect_refused", "via": "urllib"}
    except urllib.error.HTTPError as e:
        status, ctype = int(e.code), e.headers.get("Content-Type", "") if e.headers else ""
        body = b""
    except (BudgetExceeded, Cancelled):
        raise
    except Exception as e:  # noqa: BLE001 — structured preflight failure
        return {"ok": False, "path": AUTH_CHECK_PATH, "error": type(e).__name__, "via": "urllib"}
    result = verify_auth_me_response(
        status=status, body=body, content_type=ctype, expected_username=expected_username
    )
    result["via"] = "urllib"
    return result


def stage_openapi_spec(
    *, work_dir: Path, target: TargetOrigin, budget: Budget, docker_network: str = ""
) -> tuple[bool, str]:
    """Fetch a real OpenAPI document (no credential) into work_dir/openapi.json."""
    work_dir.mkdir(parents=True, exist_ok=True)
    dest = work_dir / "openapi.json"
    if dest.is_file() and dest.stat().st_size >= 32:
        try:
            parsed = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and (parsed.get("openapi") or parsed.get("swagger")):
            parsed["servers"] = [{"url": target.origin}]
            dest.write_text(json.dumps(parsed), encoding="utf-8")
            return True, f"reused staged openapi.json ({dest.stat().st_size} bytes)"

    candidates: list[str] = []
    override = os.environ.get("OPENFDD_ZAP_OPENAPI_URL", "").strip()
    if override:
        candidates.append(override)
    if target.kind == "docker_network":
        candidates.append("http://central:8080/openapi.json")
    candidates.append(target.url("/openapi.json"))

    body: bytes | None = None
    for url in candidates:
        on_network = target.kind == "docker_network" and urlsplit(url).hostname in DISPOSABLE_DOCKER_ALIASES
        if not on_network and not target.in_scope(url):
            continue
        if on_network:
            name = f"openfdd-zap-openapi-{uuid.uuid4().hex[:12]}"
            res = run_owned_process(
                [
                    "docker", "run", "--rm", "--name", name,
                    "--label", "openfdd.zap.owner=run_af_disposable",
                    "--network", docker_network, CURL_IMAGE,
                    "-fsS", "--max-time", "20", "--max-redirs", "0", "--noproxy", "*", url,
                ],
                env=child_env(),
                timeout_s=budget.timeout(60),
                container_name=name,
            )
            if res.returncode != 0:
                continue
            body = res.stdout.encode("utf-8")
        else:
            import urllib.request

            try:
                with _NoRedirect.build_opener().open(
                    urllib.request.Request(url, method="GET"), timeout=budget.timeout(20)
                ) as resp:
                    body = resp.read(2_000_000)
            except (BudgetExceeded, Cancelled):
                raise
            except Exception:  # noqa: BLE001 — try next candidate
                body = None
                continue
        if body:
            break
    if not body:
        return False, "could not fetch OpenAPI from central/override/origin"
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, f"OpenAPI JSON parse failed: {type(exc).__name__}"
    if not isinstance(parsed, dict) or not (parsed.get("openapi") or parsed.get("swagger")):
        return False, "OpenAPI JSON missing openapi/swagger field"
    parsed["servers"] = [{"url": target.origin}]
    dest.write_text(json.dumps(parsed), encoding="utf-8")
    return True, f"staged openapi.json ({dest.stat().st_size} bytes)"


# --------------------------------------------------------------------------- #
# ZAP invocation
# --------------------------------------------------------------------------- #


def zap_env(*, scanner_header: str, target: TargetOrigin) -> dict[str, str]:
    return child_env(
        {
            "ZAP_AUTH_HEADER_VALUE": scanner_header,
            "ZAP_AUTH_HEADER": "Authorization",
            # Substring match in ZAP; the HAR scope check rejects any
            # out-of-scope request that carried the header.
            "ZAP_AUTH_HEADER_SITE": target.site_key,
        }
    )


def run_zap(
    *,
    mode: str,
    detail: str,
    work_dir: Path,
    target: TargetOrigin,
    scanner_header: str,
    docker_network: str,
    budget: Budget,
) -> ProcResult:
    env = zap_env(scanner_header=scanner_header, target=target)
    if mode == "docker":
        name = f"openfdd-zap-af-scan-{uuid.uuid4().hex[:12]}"
        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--label", "openfdd.zap.owner=run_af_disposable",
            "-v", f"{work_dir}:/zap/wrk:rw",
            # Names only: docker copies the values from this process env.
            "-e", "ZAP_AUTH_HEADER_VALUE", "-e", "ZAP_AUTH_HEADER", "-e", "ZAP_AUTH_HEADER_SITE",
            "-u", "0:0",
        ]
        cmd += ["--network=host"] if target.kind == "loopback" else ["--network", docker_network]
        cmd += [detail, "zap.sh", "-cmd", "-autorun", "/zap/wrk/af_plan.yaml"]
        print(f"Running ZAP AF via docker (image={detail}, container={name})", flush=True)
        return run_owned_process(
            cmd, env=env, timeout_s=budget.timeout(budget.max_wall_seconds), container_name=name
        )
    print(f"Running ZAP AF via zap.sh ({detail})", flush=True)
    return run_owned_process(
        [detail, "-cmd", "-autorun", str(work_dir / "af_plan.yaml")],
        env=env,
        timeout_s=budget.timeout(budget.max_wall_seconds),
        cwd=str(work_dir),
    )


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


def run_selftest(verdict_path: Path) -> int:
    """Prove plan hygiene + verdict schema; never claim PASS without a scan."""
    hygiene = validate_af_plan(PLAN_PATH)
    mode, detail = detect_zap()
    disp_errors: list[str] = []
    try:
        load_dispositions()
    except EvidenceError as exc:
        disp_errors.append(str(exc))
    sample = build_verdict(
        status="BLOCKED",
        mode="selftest",
        plan_hygiene_ok=not hygiene,
        plan_hygiene_errors=hygiene,
        disposition_errors=disp_errors,
        high_alerts=None,
        medium_alerts=None,
        site_count=None,
        alert_counts_evaluated=False,
        zap_available=mode is not None,
        zap_detection=detail if mode is None else mode,
        active_scan=False,
        execute_requested=False,
        notes=(
            "Selftest only: plan hygiene + dispositions + verdict schema. Not a scan PASS. "
            "Soft-OPEN until OPENFDD_ZAP_AF_EXECUTE=1 against a disposable target "
            "produces scanner-verified authentication and High=0."
        ),
    )
    schema_errs = verdict_schema_ok(sample)
    if hygiene or schema_errs or disp_errors:
        sample["status"] = "ERROR"
        sample["notes"] = redact("Selftest failed: " + "; ".join(hygiene + schema_errs + disp_errors))
        write_verdict(verdict_path, sample)
        print(json.dumps(sample, indent=2))
        print("ERROR: selftest hygiene/schema failed", file=sys.stderr)
        return 1
    write_verdict(verdict_path, sample)
    print(json.dumps(sample, indent=2))
    print(f"BLOCKED: selftest OK (hygiene+schema); Soft-OPEN → {verdict_path}", file=sys.stderr)
    return 2


_EXIT = {"PASS": 0, "FAIL": 1, "ERROR": 1, "BLOCKED": 2}


class _Run:
    """Accumulates verdict fields for one execute run."""

    def __init__(self, verdict_path: Path, *, negative_control: bool) -> None:
        self.verdict_path = verdict_path
        self.negative_control = negative_control
        self.secrets = SecretSet()
        self.fields: dict[str, Any] = {
            "mode": "negative_control" if negative_control else "execute",
            "plan_hygiene_ok": False,
            "high_alerts": None,
            "medium_alerts": None,
            "site_count": None,
            "alert_counts_evaluated": False,
            # Traditional JSON does not expose a complete scanner error count.
            # A process return code is completion evidence, not a count of errors.
            "scanner_error_count": None,
            "scanner_error_count_status": "not_reported_by_traditional_json",
            "zap_available": False,
            "active_scan": False,
            "execute_requested": True,
            "scanner_auth_verified": False,
            "auth_proof": "none",
        }
        self.cleanup_roots: list[Path] = []

    def finish(self, status: str, notes: str, **extra: Any) -> int:
        self.fields.update(extra)
        leaked = self.secrets.sweep(self.cleanup_roots)
        if leaked:
            status = "ERROR"
            notes = f"ERROR: secret material found and deleted from artifacts {sorted(leaked)}; " + notes
            self.fields["secret_sweep_deleted"] = sorted(leaked)
        v = build_verdict(
            secrets=self.secrets,
            suite=NEGATIVE_SUITE if self.negative_control else SUITE,
            status=status,
            notes=notes,
            **self.fields,
        )
        write_verdict(self.verdict_path, v)
        print(json.dumps(v, indent=2))
        print(f"{status}: → {self.verdict_path}", file=sys.stderr)
        return _EXIT[status]


def run_execute(verdict_path: Path, *, negative_control: bool = False) -> int:
    run = _Run(verdict_path, negative_control=negative_control)
    try:
        return _execute(run)
    except Cancelled:
        return run.finish("ERROR", "ERROR: cancelled; owned processes/containers terminated")
    except BudgetExceeded as exc:
        return run.finish("FAIL", f"FAIL: {exc}; owned processes/containers terminated")


def _execute(run: _Run) -> int:
    hygiene = validate_af_plan(PLAN_PATH)
    if hygiene:
        run.fields["plan_hygiene_errors"] = hygiene
        return run.finish("ERROR", "af_plan.yaml hygiene failed: " + "; ".join(hygiene))
    run.fields["plan_hygiene_ok"] = True
    try:
        budget = load_budget()
    except ConfigError as exc:
        return run.finish("ERROR", f"ERROR: {exc}")
    run.fields["budget"] = {
        "max_wall_seconds": budget.max_wall_seconds,
        "max_requests": budget.max_requests,
        "wall_clock_enforcement": "owned_process_termination",
        "request_limit_enforcement": "post_scan_har_check",
        "request_limit_preventive": False,
    }

    origin_raw = (os.environ.get("ZAP_TARGET_ORIGIN") or "").strip()
    have_cred = bool(
        (os.environ.get("ZAP_AUTH_HEADER_VALUE") or "").strip()
        or (os.environ.get("ZAP_AUTH_HEADER_FILE") or "").strip()
    )
    expected_username = (os.environ.get("OPENFDD_ZAP_EXPECTED_USERNAME") or "").strip()
    if not origin_raw or not have_cred or not expected_username:
        return run.finish(
            "BLOCKED",
            "BLOCKED: set ZAP_TARGET_ORIGIN, OPENFDD_ZAP_EXPECTED_USERNAME and "
            "ZAP_AUTH_HEADER_FILE (or ZAP_AUTH_HEADER_VALUE) in env (never argv). "
            "Disposable target only.",
        )

    # Scope is decided before any credential is read or sent.
    docker_network = (os.environ.get("ZAP_DOCKER_NETWORK") or "").strip()
    try:
        target = parse_disposable_origin(origin_raw, docker_network=docker_network)
    except ScopeError as exc:
        return run.finish("FAIL", f"FAIL: refused target before passing credentials ({exc})")
    run.fields.update(target_origin=target.origin, target_kind=target.kind, scope_regex=target.scope_regex)
    if not _USERNAME_RE.match(expected_username):
        return run.finish("ERROR", "ERROR: OPENFDD_ZAP_EXPECTED_USERNAME must match [A-Za-z0-9._@-]{1,64}")
    run.fields["expected_username"] = expected_username

    try:
        auth = load_scanner_auth_header()
    except ConfigError as exc:
        return run.finish("ERROR", f"ERROR: {exc}")
    run.secrets.add(auth)
    nonce = uuid.uuid4().hex
    scanner_header = auth
    if run.negative_control:
        scanner_header = f"Bearer openfdd-negative-control-{nonce}"
        run.secrets.add(scanner_header)
    run.fields["auth_header_configured"] = True

    preflight = fetch_auth_me_preflight(
        target=target,
        auth_header=auth,
        expected_username=expected_username,
        budget=budget,
        docker_network=docker_network,
    )
    run.fields["auth_me_preflight"] = preflight
    if not preflight.get("ok"):
        return run.finish(
            "FAIL",
            "FAIL: independent /api/auth/me preflight did not return 200 JSON with the "
            "expected identity (precondition, not scanner proof)",
        )

    mode, detail = detect_zap()
    active = os.environ.get("OPENFDD_ZAP_AF_ACTIVE", "").strip() in ("1", "true", "yes")
    active = active and not run.negative_control
    run.fields.update(zap_available=mode is not None, zap_detection=detail if mode is None else mode, active_scan=active)
    require_digest = os.environ.get("OPENFDD_ZAP_REQUIRE_DIGEST", "").strip() in ("1", "true", "yes")
    if mode is None:
        return run.finish("BLOCKED", "BLOCKED: ZAP not available. Not a fake High=0 PASS.")
    if mode == "docker":
        run.fields.update(zap_image=detail, zap_image_digest_pinned=zap_image_is_digest_pinned(detail))
        if require_digest and not zap_image_is_digest_pinned(detail):
            return run.finish("FAIL", "FAIL: OPENFDD_ZAP_REQUIRE_DIGEST=1 but scanner image is not @sha256: pinned")

    work_root = Path(os.environ.get("ZAP_AF_WORK_DIR") or tempfile.mkdtemp(prefix="openfdd_zap_af_"))
    work_root.mkdir(parents=True, exist_ok=True)
    run.fields["work_dir"] = str(work_root)
    run.cleanup_roots.append(work_root)
    report_path = work_root / REPORT_FILE
    har_path = work_root / MESSAGES_FILE
    if report_path.exists() or har_path.exists():
        return run.finish("ERROR", "ERROR: work dir already holds scanner output; stale evidence refused")

    if not run.negative_control:
        staged_ok, staged_detail = stage_openapi_spec(
            work_dir=work_root, target=target, budget=budget, docker_network=docker_network
        )
        if not staged_ok:
            return run.finish("FAIL", f"FAIL: OpenAPI staging failed ({staged_detail})")

    plan = materialize_plan(
        target=target,
        report_dir="/zap/wrk" if mode == "docker" else str(work_root),
        active=active,
        nonce=nonce,
        expected_username=expected_username,
        max_seconds=max(60, int(budget.remaining()) - 30),
        dest=work_root / "af_plan.yaml",
        secrets=run.secrets,
        negative_control=run.negative_control,
    )

    if mode == "docker":
        inspect = run_owned_process(
            ["docker", "image", "inspect", detail], env=child_env(), timeout_s=budget.timeout(60)
        )
        if inspect.returncode != 0:
            pull = run_owned_process(["docker", "pull", detail], env=child_env(), timeout_s=budget.timeout(900))
            if pull.returncode != 0:
                return run.finish("BLOCKED", "BLOCKED: could not pull/inspect ZAP image")

    scan_started_ns = time.time_ns()
    try:
        proc = run_zap(
            mode=mode,
            detail=detail,
            work_dir=work_root,
            target=target,
            scanner_header=scanner_header,
            docker_network=docker_network,
            budget=budget,
        )
    finally:
        har_bytes: bytes | None = None
        if har_path.is_file():
            har_bytes = har_path.read_bytes()
            har_path.unlink()
    (work_root / "zap_af.stdout.log").write_text(run.secrets.scrub(proc.stdout), encoding="utf-8")
    (work_root / "zap_af.stderr.log").write_text(run.secrets.scrub(proc.stderr), encoding="utf-8")
    run.fields.update(zap_exit_code=proc.returncode, zap_duration_s=round(proc.duration_s, 1))
    if proc.cancelled:
        raise Cancelled("cancelled")
    if proc.timed_out:
        return run.finish("FAIL", "FAIL: wall-clock budget exhausted; scanner terminated and owned container removed")

    if har_bytes is not None:
        run.fields["scanner_messages"] = {
            "sha256": sha256_bytes(har_bytes),
            "bytes": len(har_bytes),
            "retained": False,
            "reason": "contains request headers; hashed, summarized, deleted",
        }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + nonce[:8]
    evidence_dir = run.verdict_path.parent / f"zap_af_{run_id}"
    run.cleanup_roots.append(evidence_dir)
    run.fields["evidence_dir"] = _rel(evidence_dir)
    if run.negative_control:
        return _finish_negative_control(run, har_bytes, target, nonce, scanner_header, budget, evidence_dir,
                                        scanner_exit_code=proc.returncode)

    # Raw report: read once, hash, never rewritten.
    if not report_path.is_file() or report_path.stat().st_size == 0:
        return run.finish("FAIL" if proc.returncode else "BLOCKED", f"ZAP produced no usable JSON report (rc={proc.returncode})")
    raw_report = report_path.read_bytes()
    raw_sha = sha256_bytes(raw_report)
    run.fields["raw_report"] = {"path": _rel(report_path), "sha256": raw_sha, "bytes": len(raw_report)}
    if report_path.stat().st_mtime_ns < scan_started_ns:
        return run.finish("ERROR", "ERROR: ZAP report predates this scan run; stale evidence rejected")
    if run.secrets.found_in(raw_report):
        report_path.unlink()
        return run.finish("ERROR", "ERROR: raw scanner report contained the scanner credential; deleted, not archived")
    report_path.chmod(stat.S_IRUSR | stat.S_IRGRP)

    archived_sha = write_once(evidence_dir / "raw" / REPORT_FILE, raw_report)
    if archived_sha != raw_sha:
        return run.finish("ERROR", "ERROR: archived raw report hash mismatch")
    run.fields["raw_report"]["archive"] = _rel(evidence_dir / "raw" / REPORT_FILE)

    if proc.returncode != 0:
        return run.finish("FAIL", f"FAIL: ZAP scanner exited nonzero (rc={proc.returncode}); report is not a PASS")

    try:
        report = parse_traditional_report(json.loads(raw_report.decode("utf-8")), target)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return run.finish("ERROR", f"ERROR: raw ZAP report is not JSON ({type(exc).__name__})")
    except EvidenceError as exc:
        return run.finish("ERROR", f"ERROR: malformed ZAP report: {exc}")
    run.fields.update(site_count=len(report.site_names), zap_version=report.version)

    if har_bytes is None:
        return run.finish("FAIL", "FAIL: ZAP message history (HAR export) missing; no scanner auth proof")
    try:
        entries = parse_scanner_messages(har_bytes)
    except EvidenceError as exc:
        return run.finish("ERROR", f"ERROR: malformed ZAP message history: {exc}")
    auth_ev = evaluate_scanner_auth(
        entries,
        target=target,
        nonce=nonce,
        expected_auth_header=auth,
        expected_username=expected_username,
        max_requests=budget.max_requests,
    )
    drain = passive_drain_errors(proc.stdout, expected_passive_waits(plan))
    auth_ev["passive_drain_errors"] = drain

    try:
        dispositions = load_dispositions()
    except EvidenceError as exc:
        return run.finish("ERROR", f"ERROR: dispositions invalid: {exc}")
    accepted, unaccepted = apply_dispositions(report.instances, dispositions)
    by_risk = report.by_risk()
    derived_alerts = {
        "raw_report_sha256": raw_sha,
        "by_risk_instances": by_risk,
        "instances": [i.as_dict() for i in report.instances],
        "medium_accepted": accepted,
        "medium_unaccepted": unaccepted,
    }
    for name, payload in (("alerts.derived.json", derived_alerts), ("auth_evidence.derived.json", auth_ev)):
        text = json.dumps(payload, indent=2) + "\n"
        if run.secrets.found_in(text):
            return run.finish("ERROR", f"ERROR: derived {name} would contain secret material")
        run.fields.setdefault("derived", {})[name] = {
            "path": _rel(evidence_dir / name),
            "sha256": write_once(evidence_dir / name, text.encode("utf-8")),
        }

    high = by_risk["High"]
    run.fields.update(
        alert_counts_evaluated=True,
        high_alerts=high,
        medium_alerts=by_risk["Medium"],
        medium_undispositioned=len(unaccepted),
        medium_dispositions_applied=sorted({a["disposition_id"] for a in accepted}),
        alert_instance_count=len(report.instances),
        high_alert_names=sorted({i.name for i in report.instances if i.risk == "High"}),
        scanner_auth=auth_ev,
    )
    if report.stopping_insight:
        return run.finish("FAIL", "FAIL: ZAP reported a stoppingInsight (scan stopped early)")
    if not auth_ev["ok"]:
        return run.finish(
            "FAIL",
            "FAIL: scanner-origin authentication not proven from ZAP message history ("
            + "; ".join(auth_ev["errors"][:6])
            + ")",
        )
    run.fields.update(scanner_auth_verified=True, auth_proof="zap_message_history_probes_before_during_after")
    if drain:
        return run.finish("FAIL", "FAIL: " + "; ".join(drain))
    if high > 0:
        return run.finish("FAIL", f"FAIL: High={high} ({', '.join(run.fields['high_alert_names'][:8])})")
    if unaccepted:
        sample = ", ".join(f"{u['plugin_id']} {u['method']} {u['route']} param={u['param']!r}" for u in unaccepted[:5])
        return run.finish("FAIL", f"FAIL: {len(unaccepted)} unaccepted Medium instance(s): {sample}")
    return run.finish(
        "PASS",
        f"PASS: disposable AF High=0 Medium_unaccepted=0 Medium_instances={by_risk['Medium']} "
        f"sites={len(report.site_names)} scanner_auth=before/during/after active_scan={active} "
        f"requests={auth_ev['request_count']}",
    )


def _finish_negative_control(
    run: _Run,
    har_bytes: bytes | None,
    target: TargetOrigin,
    nonce: str,
    scanner_auth: str,
    budget: Budget,
    evidence_dir: Path,
    *,
    scanner_exit_code: int | None,
) -> int:
    """Only observed rejection of the exact bad credential can qualify this control."""
    if har_bytes is None:
        return run.finish("ERROR", "ERROR: negative control inconclusive (no ZAP message history)")
    try:
        entries = parse_scanner_messages(har_bytes)
    except EvidenceError as exc:
        return run.finish("ERROR", f"ERROR: negative control inconclusive ({exc})")
    auth_ev = evaluate_negative_control(
        entries,
        target=target,
        nonce=nonce,
        scanner_auth_header=scanner_auth,
        max_requests=budget.max_requests,
    )
    payload = (json.dumps(auth_ev, indent=2) + "\n").encode("utf-8")
    run.fields["derived"] = {"auth_evidence.derived.json": {
        "path": _rel(evidence_dir / "auth_evidence.derived.json"),
        "sha256": write_once(evidence_dir / "auth_evidence.derived.json", payload),
    }}
    run.fields["scanner_auth"] = auth_ev
    if auth_ev["unexpected_success_count"]:
        return run.finish("FAIL", "FAIL: negative control — an auth probe returned HTTP 200 with a broken credential")
    if scanner_exit_code != 0:
        return run.finish("ERROR", f"ERROR: negative control inconclusive (scanner exited {scanner_exit_code})")
    if not auth_ev["ok"]:
        return run.finish("ERROR", "ERROR: negative control inconclusive (" + "; ".join(auth_ev["errors"][:6]) + ")")
    return run.finish(
        "PASS",
        "PASS: negative control — broken scanner credential rejected while preflight succeeded",
        negative_control_detected=True,
        auth_proof="zap_message_history_bad_credential_denials_before_during_after",
    )


def _install_cancel_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def _handler(signum, _frame):
        _CANCEL.set()

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        try:
            previous[sig] = signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass
    return previous


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true", help="plan hygiene + verdict schema; exit BLOCKED (2)")
    p.add_argument(
        "--negative-control",
        action="store_true",
        help="run with a broken scanner credential; exit 0 only if the evaluator rejects it",
    )
    p.add_argument("--out", default=None, help=f"verdict JSON path (default: {DEFAULT_VERDICT})")
    args = p.parse_args(argv)
    default = DEFAULT_NEGATIVE_VERDICT if args.negative_control else DEFAULT_VERDICT
    out = Path(args.out) if args.out else default

    if args.selftest:
        return run_selftest(out)

    execute = os.environ.get("OPENFDD_ZAP_AF_EXECUTE", "").strip() in ("1", "true", "yes")
    if not execute:
        print(
            "BLOCKED: set OPENFDD_ZAP_AF_EXECUTE=1 for a real disposable scan, "
            "or pass --selftest for hygiene-only BLOCKED evidence.",
            file=sys.stderr,
        )
        hygiene = validate_af_plan(PLAN_PATH)
        v = build_verdict(
            status="BLOCKED",
            mode="idle",
            plan_hygiene_ok=not hygiene,
            plan_hygiene_errors=hygiene,
            high_alerts=None,
            medium_alerts=None,
            site_count=None,
            alert_counts_evaluated=False,
            zap_available=detect_zap()[0] is not None,
            active_scan=False,
            execute_requested=False,
            notes="OPENFDD_ZAP_AF_EXECUTE not set — refusing to invent a scan PASS.",
        )
        write_verdict(out, v)
        print(json.dumps(v, indent=2))
        return 2

    _CANCEL.clear()
    previous = _install_cancel_handlers()
    try:
        return run_execute(out, negative_control=args.negative_control)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
