#!/usr/bin/env python3
"""Standalone HTTPS bootstrap probe (Wave U U3 Soft-OPEN / UA-02).

Default / --selftest: lint compose + Caddyfile + exposure manifest (no Docker).
Optional peer soak: OPENFDD_HTTPS_PEER_PROBE=1 or --peer-probe brings up an
isolated Compose project (official caddy + stub web, self-signed certs) and
asserts TLS health with a trusted CA context, untrusted-store rejection, and
HTTP login refusal/redirect.

Candidate soak: --candidate-probe (or OPENFDD_HTTPS_CANDIDATE_PROBE=1) uses
product GHCR images (central/web/mqtt + official caddy), not the stub web.
Immutable artifact dir under reports/security/standalone_https_peer_<UTC>/.

Never claims a Nessus PASS. Stub peer soak ≠ product-image candidate qualification.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker" / "compose.standalone.https.yml"
CADDYFILE = ROOT / "deploy" / "caddy" / "Caddyfile.standalone.https"
EXPOSURE = ROOT / "scripts" / "security" / "exposure" / "standalone_https.json"
DEFAULT_OUT = ROOT / "reports" / "security" / "standalone_https_probe.json"
ARTIFACT_ROOT = ROOT / "reports" / "security"

SCHEMA = "openfdd_standalone_https_probe_v1"
PRODUCT_IMAGE_RE = re.compile(
    r"^ghcr\.io/bbartling/openfdd-(central|web|mqtt)(:|$)",
    re.IGNORECASE,
)
STUB_IMAGE_MARKERS = (
    "python:",
    "python@",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lint_compose(text: str) -> list[str]:
    errs: list[str] = []
    if "caddy:" not in text:
        errs.append("compose missing caddy service")
    if "443:443" not in text and '"443:443"' not in text:
        errs.append("compose must publish HTTPS 443:443")
    if "80:80" not in text and '"80:80"' not in text:
        errs.append("compose must publish HTTP 80:80 (redirect/ACME only)")
    if re.search(r"8080:8080", text):
        errs.append("HTTPS overlay must not publish central 8080")
    if "Caddyfile.standalone.https" not in text:
        errs.append("compose must mount Caddyfile.standalone.https")
    if "caddy:2" not in text.lower() and "image: caddy" not in text.lower():
        errs.append("compose must use official caddy image")
    # Overlay may mention fieldbus env hardening; must not open management.
    if re.search(r"0\.0\.0\.0:8081", text):
        errs.append("HTTPS overlay must not publish fieldbus management")
    return errs


def lint_caddyfile(text: str) -> list[str]:
    errs: list[str] = []
    if "tls " not in text and "tls\n" not in text:
        errs.append("Caddyfile must enable tls")
    if "reverse_proxy" not in text:
        errs.append("Caddyfile must reverse_proxy to web")
    if "Strict-Transport-Security" not in text:
        errs.append("Caddyfile should set Strict-Transport-Security")
    if not re.search(r"(?m)^http://", text):
        errs.append("Caddyfile must declare http:// redirect site (no plaintext login)")
    if "redir" not in text.lower():
        errs.append("Caddyfile must redirect HTTP→HTTPS")
    # Refuse an HTTP-only site that reverse_proxies (plaintext login path).
    for m in re.finditer(
        r"(?m)^(http://[^\s{]+|:80)\s*\{([^}]*)\}",
        text,
        flags=re.DOTALL,
    ):
        body = m.group(2)
        if "reverse_proxy" in body and "redir" not in body.lower():
            errs.append(
                f"plaintext site {m.group(1)!r} reverse_proxies without redirect"
            )
    if re.search(r"(?m)^:80\s*\{[^}]*reverse_proxy", text, flags=re.DOTALL):
        if "redir" not in text.lower():
            errs.append(":80 block must not reverse_proxy without redir")
    return errs


def lint_exposure(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if data.get("schema_version") != "openfdd_exposure_manifest_v1":
        errs.append("bad exposure schema_version")
    if data.get("profile") != "standalone_https":
        errs.append("exposure profile must be standalone_https")
    services = data.get("services") or []
    caddy_443 = False
    caddy_80 = False
    central_loopback = False
    for svc in services:
        name = svc.get("service")
        iface = svc.get("interface")
        for port in svc.get("ports") or []:
            p = port.get("port")
            auth = str(port.get("auth") or "")
            if name == "caddy" and p == 443:
                caddy_443 = True
                if "tls" not in auth:
                    errs.append("caddy:443 auth must include tls")
            if name == "caddy" and p == 80:
                caddy_80 = True
                denied = [d.lower() for d in (svc.get("denied") or [])]
                if not any("plaintext" in d or "login" in d for d in denied):
                    errs.append("caddy:80 must deny plaintext login")
                if "redirect" not in auth and "acme" not in auth:
                    errs.append("caddy:80 auth must be redirect_or_acme")
            if name == "central" and p == 8080:
                if iface != "127.0.0.1":
                    errs.append("central:8080 must be interface 127.0.0.1")
                else:
                    central_loopback = True
    if not caddy_443:
        errs.append("exposure missing caddy:443")
    if not caddy_80:
        errs.append("exposure missing caddy:80")
    if not central_loopback:
        errs.append("exposure missing loopback central:8080")
    return errs


def run_config_lint() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    compose_text = COMPOSE.read_text(encoding="utf-8")
    caddy_text = CADDYFILE.read_text(encoding="utf-8")
    exposure = json.loads(EXPOSURE.read_text(encoding="utf-8"))

    for name, errs in (
        ("compose_standalone_https", lint_compose(compose_text)),
        ("caddyfile_standalone_https", lint_caddyfile(caddy_text)),
        ("exposure_standalone_https", lint_exposure(exposure)),
    ):
        checks.append(
            {
                "id": name,
                "ok": not errs,
                "errors": errs,
            }
        )
    ok = all(c["ok"] for c in checks)
    return {
        "schema_version": SCHEMA,
        "mode": "config_lint",
        "ok": ok,
        "verdict": "PASS" if ok else "FAIL",
        "checked_at": _now(),
        "assets": {
            "compose": str(COMPOSE.relative_to(ROOT)),
            "caddyfile": str(CADDYFILE.relative_to(ROOT)),
            "exposure": str(EXPOSURE.relative_to(ROOT)),
        },
        "checks": checks,
        "note": (
            "Config lint only — not a live scan and not a Nessus PASS. "
            "Peer soak requires OPENFDD_HTTPS_PEER_PROBE=1."
        ),
    }


def _openssl_self_signed(cert_dir: Path) -> None:
    cert_dir.mkdir(parents=True, exist_ok=True)
    crt = cert_dir / "server.crt"
    key = cert_dir / "server.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(crt),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    key.chmod(0o600)


def assert_product_images(images: dict[str, str]) -> list[str]:
    """Reject stub/non-product refs when claiming candidate mode."""
    errs: list[str] = []
    for role, ref in images.items():
        low = (ref or "").lower()
        if any(m in low for m in STUB_IMAGE_MARKERS):
            errs.append(f"{role} image looks like stub/non-product: {ref}")
        if role in ("central", "web", "mqtt") and not PRODUCT_IMAGE_RE.match(ref or ""):
            errs.append(f"{role} must be ghcr.io/bbartling/openfdd-{role}:… got {ref}")
        if role == "caddy" and "caddy" not in low:
            errs.append(f"caddy image must be official caddy, got {ref}")
    return errs


def resolve_candidate_images(tag: str) -> dict[str, str]:
    tag = (tag or "").strip()
    if not tag:
        raise ValueError("candidate probe requires OPENFDD_IMAGE_TAG or --image-tag")
    if not tag.startswith("sha-") and tag != "nightly":
        # allow full digests/tags but prefer sha-*
        pass
    return {
        "central": f"ghcr.io/bbartling/openfdd-central:{tag}",
        "web": f"ghcr.io/bbartling/openfdd-web:{tag}",
        "mqtt": f"ghcr.io/bbartling/openfdd-mqtt:{tag}",
        "caddy": "caddy:2.8-alpine",
    }


def _write_probe_compose(path: Path, cert_dir: Path, http_port: int, https_port: int) -> None:
    # Isolated project: official caddy + stub web. No product image builds.
    body = f"""# Generated by peer_probe_https.py — do not commit.
name: openfdd-https-peer-probe
services:
  web:
    image: python:3.12-alpine
    command:
      - python3
      - -c
      - |
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/api/health"):
                    body = b'{{"status":"ok","probe":"standalone-https"}}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/auth") or "/login" in self.path:
                    body = b"login-should-not-be-plaintext"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
            def log_message(self, *args):
                pass
        HTTPServer(("0.0.0.0", 8080), H).serve_forever()
    expose:
      - "8080"

  caddy:
    image: caddy:2.8-alpine
    ports:
      - "{https_port}:443"
      - "{http_port}:80"
    volumes:
      - {CADDYFILE.resolve()}:/etc/caddy/Caddyfile:ro
      - {cert_dir.resolve()}:/certs:ro
    depends_on:
      - web
    environment:
      OPENFDD_PUBLIC_HOST: localhost
"""
    path.write_text(body, encoding="utf-8")


def _write_candidate_compose(
    path: Path,
    *,
    cert_dir: Path,
    workspace: Path,
    images: dict[str, str],
    http_port: int,
    https_port: int,
    jwt_secret: str,
    admin_password: str,
) -> None:
    """Product GHCR stack behind Caddy — MQTT disabled on central for soak simplicity."""
    mqtt_certs = (ROOT / "deploy" / "mqtt" / "certs").resolve()
    # Prefer example ACL (readable); live site acl may be root-only.
    mqtt_acl = ROOT / "deploy" / "mqtt" / "acl.example"
    if not mqtt_acl.is_file():
        mqtt_acl = ROOT / "deploy" / "mqtt" / "acl"
    mqtt_acl = mqtt_acl.resolve()
    body = f"""# Generated by peer_probe_https.py candidate mode — do not commit.
name: openfdd-https-candidate-probe
services:
  mqtt:
    image: {images["mqtt"]}
    volumes:
      - {mqtt_certs}:/mosquitto/certs:ro
      - {mqtt_acl}:/mosquitto/config/acl:ro
    expose:
      - "8883"

  central:
    image: {images["central"]}
    environment:
      OPENFDD_MQTT_ENABLED: "0"
      OPENFDD_WORKSPACE: /workspace
      OPENFDD_STORAGE_URL: file:///workspace/openfdd
      OPENFDD_JWT_SECRET: "{jwt_secret}"
      OPENFDD_ADMIN_PASSWORD: "{admin_password}"
    volumes:
      - {workspace.resolve()}:/workspace
    expose:
      - "8080"
    depends_on:
      - mqtt

  web:
    image: {images["web"]}
    environment:
      OPENFDD_CENTRAL_UPSTREAM: central:8080
      OPENFDD_NGINX_RESOLVER: auto
    expose:
      - "8080"
    depends_on:
      - central

  caddy:
    image: {images["caddy"]}
    ports:
      - "{https_port}:443"
      - "{http_port}:80"
    volumes:
      - {CADDYFILE.resolve()}:/etc/caddy/Caddyfile:ro
      - {cert_dir.resolve()}:/certs:ro
    depends_on:
      - web
    environment:
      OPENFDD_PUBLIC_HOST: localhost
"""
    path.write_text(body, encoding="utf-8")


def _tls_soak_checks(
    *,
    cert_dir: Path,
    http_port: int,
    https_port: int,
    health_wait_s: float = 90.0,
) -> list[dict[str, Any]]:
    """Shared trusted-CA HTTPS + untrusted reject + plaintext login checks."""
    checks: list[dict[str, Any]] = []
    trust = _ssl_trust_ca(cert_dir / "server.crt")
    https_url = f"https://localhost:{https_port}/api/health"
    deadline = time.time() + health_wait_s
    health: dict[str, Any] = {}
    while time.time() < deadline:
        health = _http_probe(https_url, ssl_context=trust)
        if health.get("ok") and health.get("status") == 200:
            break
        time.sleep(1.5)
    checks.append(
        {
            "id": "https_api_health_trusted_ca",
            "ok": bool(health.get("ok") and health.get("status") == 200),
            "detail": health,
        }
    )

    import ssl as _ssl

    default_ctx = _ssl.create_default_context()
    untrusted = _http_probe(https_url, ssl_context=default_ctx)
    checks.append(
        {
            "id": "https_rejects_untrusted_default_store",
            "ok": not untrusted.get("ok"),
            "detail": untrusted,
        }
    )

    login_paths = ("/auth", "/api/auth/login", "/login")
    plaintext_ok = True
    plaintext_details: list[dict[str, Any]] = []
    for path in login_paths:
        http_url = f"http://localhost:{http_port}{path}"
        try:
            hdrs = _http_headers(http_url)
        except Exception as e:  # noqa: BLE001
            plaintext_details.append({"path": path, "error": str(e), "refused": True})
            continue
        status = int(hdrs.get("status") or 0)
        location = (hdrs.get("location") or "").lower()
        body = (hdrs.get("body_prefix") or "").lower()
        redirected = status in (301, 302, 307, 308) and "https" in location
        refused_login = status in (400, 403, 404, 405, 421, 495, 496, 497)
        serves_login = "login-should-not-be-plaintext" in body or (
            status == 200 and "login" in body
        )
        path_ok = (redirected or refused_login) and not serves_login
        if not path_ok:
            plaintext_ok = False
        plaintext_details.append(
            {
                "path": path,
                "status": status,
                "location": hdrs.get("location"),
                "ok": path_ok,
            }
        )
    checks.append(
        {
            "id": "http_login_refused_or_redirected",
            "ok": plaintext_ok,
            "detail": plaintext_details,
        }
    )
    return checks


def run_candidate_probe(
    *,
    image_tag: str | None = None,
    http_port: int | None = None,
    https_port: int | None = None,
    keep: bool = False,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Product-image HTTPS soak (UA-02 candidate). Stub peer ≠ this mode."""
    http_port = http_port or int(os.environ.get("OPENFDD_HTTPS_PROBE_HTTP_PORT", "18080"))
    https_port = https_port or int(os.environ.get("OPENFDD_HTTPS_PROBE_HTTPS_PORT", "18443"))
    tag = (
        image_tag
        or os.environ.get("OPENFDD_IMAGE_TAG")
        or os.environ.get("OPENFDD_HTTPS_CANDIDATE_TAG")
        or ""
    ).strip()

    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    art = artifact_dir or (ARTIFACT_ROOT / f"standalone_https_peer_{utc}")
    art.mkdir(parents=True, exist_ok=True)

    if shutil.which("docker") is None:
        report = {
            "schema_version": SCHEMA,
            "mode": "candidate_probe",
            "ok": False,
            "verdict": "FAIL",
            "checked_at": _now(),
            "error": "docker not installed",
            "artifact_dir": str(art),
        }
        write_verdict(art / "verdict.json", report)
        return report

    try:
        images = resolve_candidate_images(tag)
    except ValueError as e:
        report = {
            "schema_version": SCHEMA,
            "mode": "candidate_probe",
            "ok": False,
            "verdict": "FAIL",
            "checked_at": _now(),
            "error": str(e),
            "artifact_dir": str(art),
        }
        write_verdict(art / "verdict.json", report)
        return report

    img_errs = assert_product_images(images)
    checks: list[dict[str, Any]] = [
        {
            "id": "product_images_not_stub",
            "ok": not img_errs,
            "errors": img_errs,
            "images": images,
            "image_tag": tag,
        }
    ]
    if img_errs:
        report = {
            "schema_version": SCHEMA,
            "mode": "candidate_probe",
            "ok": False,
            "verdict": "FAIL",
            "checked_at": _now(),
            "checks": checks,
            "artifact_dir": str(art),
            "note": "Candidate mode rejected stub/non-product images.",
        }
        write_verdict(art / "verdict.json", report)
        return report

    tmp = Path(tempfile.mkdtemp(prefix="openfdd-https-candidate-"))
    compose_path = tmp / "compose.candidate.yml"
    cert_dir = tmp / "certs"
    workspace = tmp / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "openfdd").mkdir(exist_ok=True)
    project = f"ofdd-https-cand-{os.getpid()}"
    jwt_secret = os.environ.get("OPENFDD_JWT_SECRET") or ("probe-" + utc + "-jwt-secret-32chars!!")
    admin_password = os.environ.get("OPENFDD_ADMIN_PASSWORD") or ("probe-admin-" + utc)

    try:
        _openssl_self_signed(cert_dir)
        _write_candidate_compose(
            compose_path,
            cert_dir=cert_dir,
            workspace=workspace,
            images=images,
            http_port=http_port,
            https_port=https_port,
            jwt_secret=jwt_secret,
            admin_password=admin_password,
        )
        shutil.copy2(compose_path, art / "compose.candidate.yml")
        up = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_path),
                "up",
                "-d",
                "--pull",
                "missing",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        checks.append(
            {
                "id": "compose_up",
                "ok": up.returncode == 0,
                "stderr": (up.stderr or "")[-1200:],
                "stdout": (up.stdout or "")[-400:],
            }
        )
        if up.returncode == 0:
            checks.extend(
                _tls_soak_checks(
                    cert_dir=cert_dir,
                    http_port=http_port,
                    https_port=https_port,
                    health_wait_s=120.0,
                )
            )
        ok = all(c["ok"] for c in checks)
        report = {
            "schema_version": SCHEMA,
            "mode": "candidate_probe",
            "ok": ok,
            "verdict": "PASS" if ok else "FAIL",
            "checked_at": _now(),
            "project": project,
            "ports": {"http": http_port, "https": https_port},
            "images": images,
            "image_tag": tag,
            "artifact_dir": str(art),
            "checks": checks,
            "note": (
                "Product GHCR candidate HTTPS soak (central/web/mqtt + caddy). "
                "Trusted CA only on success path. Not a Nessus PASS."
            ),
        }
        write_verdict(art / "verdict.json", report)
        return report
    except Exception as e:  # noqa: BLE001
        report = {
            "schema_version": SCHEMA,
            "mode": "candidate_probe",
            "ok": False,
            "verdict": "FAIL",
            "checked_at": _now(),
            "error": str(e),
            "checks": checks,
            "artifact_dir": str(art),
        }
        write_verdict(art / "verdict.json", report)
        return report
    finally:
        if not keep and compose_path.is_file():
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    project,
                    "-f",
                    str(compose_path),
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            shutil.rmtree(tmp, ignore_errors=True)


def _ssl_unverified():
    """Negative-control only — never use for qualifying HTTPS success paths."""
    import ssl

    ctx = ssl._create_unverified_context()
    ctx.check_hostname = False
    return ctx


def _ssl_trust_ca(ca_pem: Path):
    """Positive path: trust the probe-generated CA/self-signed PEM (no verify=False)."""
    import ssl

    ctx = ssl.create_default_context(cafile=str(ca_pem))
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _http_probe(
    url: str,
    *,
    timeout: float = 5.0,
    ssl_context=None,
) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    ctx = ssl_context
    if ctx is None and url.startswith("https://"):
        raise ValueError("https probes require an explicit ssl_context (trusted CA or negative)")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read(512)
            return {
                "ok": True,
                "status": getattr(resp, "status", None) or resp.getcode(),
                "url": url,
                "final_url": resp.geturl(),
                "body_prefix": body[:120].decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "url": url,
            "final_url": e.geturl() if hasattr(e, "geturl") else url,
            "body_prefix": (e.read(120) if e.fp else b"").decode("utf-8", errors="replace"),
            "error": str(e),
        }
    except Exception as e:  # noqa: BLE001 — probe surface
        return {"ok": False, "url": url, "error": str(e)}


def _http_headers(url: str, *, timeout: float = 5.0, ssl_context=None) -> dict[str, Any]:
    """GET without following redirects — measure Location."""
    import http.client
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    if parsed.scheme == "https":
        if ssl_context is None:
            raise ValueError("https header probe requires ssl_context")
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            host,
            port,
            context=ssl_context,
            timeout=timeout,
        )
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"Host": "localhost"})
        resp = conn.getresponse()
        location = resp.getheader("Location")
        body = resp.read(64)
        return {
            "status": resp.status,
            "location": location,
            "body_prefix": body.decode("utf-8", errors="replace"),
        }
    finally:
        conn.close()


def run_peer_probe(
    *,
    http_port: int | None = None,
    https_port: int | None = None,
    keep: bool = False,
) -> dict[str, Any]:
    http_port = http_port or int(os.environ.get("OPENFDD_HTTPS_PROBE_HTTP_PORT", "18080"))
    https_port = https_port or int(os.environ.get("OPENFDD_HTTPS_PROBE_HTTPS_PORT", "18443"))

    if shutil.which("docker") is None:
        return {
            "schema_version": SCHEMA,
            "mode": "peer_probe",
            "ok": False,
            "verdict": "FAIL",
            "checked_at": _now(),
            "error": "docker not installed",
            "note": "Peer probe requires Docker Compose; config lint remains available.",
        }

    tmp = Path(tempfile.mkdtemp(prefix="openfdd-https-probe-"))
    compose_path = tmp / "compose.peer.yml"
    cert_dir = tmp / "certs"
    project = f"ofdd-https-probe-{os.getpid()}"
    checks: list[dict[str, Any]] = []
    try:
        _openssl_self_signed(cert_dir)
        _write_probe_compose(compose_path, cert_dir, http_port, https_port)
        up = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_path),
                "up",
                "-d",
                "--pull",
                "missing",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        checks.append(
            {
                "id": "compose_up",
                "ok": up.returncode == 0,
                "stderr": (up.stderr or "")[-800:],
                "stdout": (up.stdout or "")[-400:],
            }
        )
        if up.returncode != 0:
            return _peer_result(False, checks, tmp, project, keep, http_port, https_port)

        # Wait for caddy + stub (localhost SNI matches self-signed CN + Caddy site).
        # Positive HTTPS must trust the probe-generated PEM (no verify=False).
        trust = _ssl_trust_ca(cert_dir / "server.crt")
        https_url = f"https://localhost:{https_port}/api/health"
        deadline = time.time() + 45
        health: dict[str, Any] = {}
        while time.time() < deadline:
            health = _http_probe(https_url, ssl_context=trust)
            if health.get("ok") and health.get("status") == 200:
                break
            time.sleep(1.5)
        checks.append(
            {
                "id": "https_api_health_trusted_ca",
                "ok": bool(health.get("ok") and health.get("status") == 200),
                "detail": health,
            }
        )

        # Negative: default trust store must reject the self-signed cert.
        import ssl as _ssl

        default_ctx = _ssl.create_default_context()
        untrusted = _http_probe(https_url, ssl_context=default_ctx)
        untrusted_ok = not untrusted.get("ok")
        checks.append(
            {
                "id": "https_rejects_untrusted_default_store",
                "ok": untrusted_ok,
                "detail": untrusted,
            }
        )

        # Plaintext login must not succeed — redirect or refuse.
        login_paths = ("/auth", "/api/auth/login", "/login")
        plaintext_ok = True
        plaintext_details: list[dict[str, Any]] = []
        for path in login_paths:
            http_url = f"http://localhost:{http_port}{path}"
            try:
                hdrs = _http_headers(http_url)
            except Exception as e:  # noqa: BLE001
                plaintext_details.append({"path": path, "error": str(e), "refused": True})
                continue
            status = int(hdrs.get("status") or 0)
            location = (hdrs.get("location") or "").lower()
            body = (hdrs.get("body_prefix") or "").lower()
            redirected = status in (301, 302, 307, 308) and "https" in location
            refused_login = status in (400, 403, 404, 405, 421, 495, 496, 497)
            serves_login = "login-should-not-be-plaintext" in body or (
                status == 200 and "login" in body
            )
            path_ok = (redirected or refused_login) and not serves_login
            if not path_ok:
                plaintext_ok = False
            plaintext_details.append(
                {
                    "path": path,
                    "status": status,
                    "location": hdrs.get("location"),
                    "ok": path_ok,
                }
            )
        checks.append(
            {
                "id": "http_login_refused_or_redirected",
                "ok": plaintext_ok,
                "detail": plaintext_details,
            }
        )

        ok = all(c["ok"] for c in checks)
        return _peer_result(ok, checks, tmp, project, keep, http_port, https_port)
    except Exception as e:  # noqa: BLE001
        return {
            "schema_version": SCHEMA,
            "mode": "peer_probe",
            "ok": False,
            "verdict": "FAIL",
            "checked_at": _now(),
            "error": str(e),
            "checks": checks,
            "note": "Peer probe raised before completing soak.",
        }
    finally:
        if not keep and compose_path.is_file():
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    project,
                    "-f",
                    str(compose_path),
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            shutil.rmtree(tmp, ignore_errors=True)


def _peer_result(
    ok: bool,
    checks: list[dict[str, Any]],
    tmp: Path,
    project: str,
    keep: bool,
    http_port: int,
    https_port: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "mode": "peer_probe",
        "ok": ok,
        "verdict": "PASS" if ok else "FAIL",
        "checked_at": _now(),
        "project": project,
        "ports": {"http": http_port, "https": https_port},
        "workdir": str(tmp) if keep else None,
        "checks": checks,
        "note": (
            "Isolated Compose peer soak (caddy official + stub web, self-signed). "
            "HTTPS success path trusts the probe PEM (no verify=False). "
            "Not a Nessus PASS and not a full product-image candidate soak."
        ),
    }


def write_verdict(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--selftest",
        action="store_true",
        help="config lint only (CI default)",
    )
    p.add_argument(
        "--peer-probe",
        action="store_true",
        help="run isolated Compose HTTPS soak with stub web (or OPENFDD_HTTPS_PEER_PROBE=1)",
    )
    p.add_argument(
        "--candidate-probe",
        action="store_true",
        help="product GHCR images soak (or OPENFDD_HTTPS_CANDIDATE_PROBE=1)",
    )
    p.add_argument(
        "--image-tag",
        default="",
        help="GHCR tag for candidate mode (default OPENFDD_IMAGE_TAG)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"verdict JSON path (default {DEFAULT_OUT})",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="keep temp compose/certs and leave containers up",
    )
    args = p.parse_args(argv)

    want_peer = args.peer_probe or os.environ.get("OPENFDD_HTTPS_PEER_PROBE", "") == "1"
    want_candidate = (
        args.candidate_probe or os.environ.get("OPENFDD_HTTPS_CANDIDATE_PROBE", "") == "1"
    )
    modes = sum(bool(x) for x in (args.selftest, want_peer, want_candidate))
    if modes > 1:
        p.error("use only one of --selftest, --peer-probe, --candidate-probe")

    if want_candidate:
        config = run_config_lint()
        if not config["ok"]:
            write_verdict(args.out, config)
            print(json.dumps(config, indent=2))
            return 1
        report = run_candidate_probe(image_tag=args.image_tag or None, keep=args.keep)
        report["config_lint"] = {"ok": True, "verdict": config["verdict"]}
    elif want_peer:
        config = run_config_lint()
        if not config["ok"]:
            write_verdict(args.out, config)
            print(json.dumps(config, indent=2))
            return 1
        report = run_peer_probe(keep=args.keep)
        report["config_lint"] = {"ok": True, "verdict": config["verdict"]}
    else:
        report = run_config_lint()
        report["mode"] = "selftest" if args.selftest or not want_peer else report["mode"]

    write_verdict(args.out, report)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
