#!/usr/bin/env python3
"""Prove which front-door paths are public, quiet-denied, or basic-auth.

Runs Caddy (the same routes.caddy Full and Lite import) in front of a tiny upstream
and requests the matrix. A path is public only when the upstream sees it and the
answer has no WWW-Authenticate. A cancelled login is a request with no Authorization
header: console and write paths must be 401 and must not be proxied.

    python3 deploy/nf-caddy/test_routes.py

Caddy 2.11.9 must be on PATH (or set CADDY=/path/to/caddy). No root, no Docker.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CADDY = os.environ.get("CADDY") or shutil.which("caddy") or "/tmp/caddy"
PASSWORD = "route-test-password"
USER = "admin"

# (method, path) the dashboard may call with no login. Upstream must see them.
PUBLIC = [
    ("GET", "/api/v1/apps/static/open-fdd/"),
    ("GET", "/api/v1/apps/static/open-fdd/index.html"),
    ("GET", "/api/v1/apps/static/open-fdd-lite/nf.js"),
    ("HEAD", "/api/v1/apps/static/open-fdd/base.css"),
    ("GET", "/favicon.ico"),
    ("GET", "/favicon.png"),
    ("GET", "/favicon.svg"),
    ("GET", "/apple-touch-icon.png"),
    ("GET", "/apple-touch-icon-precomposed.png"),
    ("GET", "/api/v1/point/data?uuids=1&window=300s"),
    ("HEAD", "/api/v1/platform/info"),
    ("GET", "/api/v1/bacnet/configuration"),
    ("GET", "/api/v1/bacnet/local"),
    ("GET", "/api/v1/bacnet/ports"),
    ("GET", "/api/v1/bacnet/readproperty?property_id=PROP_PRESENT_VALUE"),
    ("GET", "/api/v1/sites?pageSize=100"),
    ("GET", "/api/v1/sites/site-1"),
    ("GET", "/api/v1/schedules?pageOffset=0&pageSize=100"),
    ("GET", "/api/v1/schedules/sched-1"),
    ("GET", "/api/v1/point/updates/data?uuids=1&wait=true"),
    ("POST", "/api/v1/point/query"),
    ("POST", "/api/v1/auth/token"),
    ("POST", "/api/v1/apps/open-fdd/hooks/schema"),
    ("POST", "/api/v1/apps/open-fdd-lite/hooks/schema"),
    ("GET", "/api/v1/apps/open-fdd/hooks/schema/runs?page_size=5&include_results=true"),
    ("GET", "/api/v1/apps/open-fdd-lite/hooks/schema/runs"),
    ("POST", "/api/v1/apps/open-fdd/hooks/analytics"),
    ("POST", "/api/v1/apps/open-fdd-lite/hooks/analytics"),
    ("GET", "/api/v1/apps/open-fdd/hooks/analytics/runs?page_size=10"),
    ("GET", "/api/v1/apps/open-fdd-lite/hooks/analytics/runs"),
]

# Anonymous callers get 403 and no login challenge. A valid login is proxied.
QUIET = [
    ("GET", "/api/v1/apps"),
    ("HEAD", "/api/v1/apps"),
    ("POST", "/api/v1/apps/open-fdd/hooks/tuning"),
    ("POST", "/api/v1/apps/open-fdd-lite/hooks/tuning"),
]

# No login: 401 + WWW-Authenticate, upstream not called. Cancelling the dialog stops here.
PROTECTED = [
    ("GET", "/"),
    ("GET", "/index.html"),
    ("GET", "/assets/index.js"),
    ("GET", "/api/v1/apps/open-fdd"),
    ("GET", "/api/v1/apps/open-fdd-lite"),
    ("GET", "/api/v1/apps/open-fdd/hooks"),
    ("POST", "/api/v1/apps"),
    ("PATCH", "/api/v1/apps/open-fdd"),
    ("DELETE", "/api/v1/apps/open-fdd"),
    ("POST", "/api/v1/apps/open-fdd/hooks/fdd"),
    ("POST", "/api/v1/apps/open-fdd-lite/hooks/fdd"),
    ("GET", "/api/v1/apps/open-fdd/hooks/fdd/runs"),
    ("POST", "/api/v1/apps/open-fdd/hooks/history"),
    ("POST", "/api/v1/apps/open-fdd-lite/hooks/history"),
    ("POST", "/api/v1/apps/open-fdd/hooks/weather"),
    ("POST", "/api/v1/apps/open-fdd/hooks/sparql"),
    ("POST", "/api/v1/apps/open-fdd/hooks/schema/runs"),
    ("POST", "/api/v1/apps/other-app/hooks/schema"),
    ("POST", "/api/v1/apps/other-app/hooks/analytics"),
    ("GET", "/api/v1/apps/other-app/hooks/schema/runs"),
    ("POST", "/api/v1/bacnet/local"),
    ("PATCH", "/api/v1/bacnet/local"),
    ("POST", "/api/v1/point/data"),
    ("GET", "/api/v1/point/query"),
    ("GET", "/api/v1/auth/token"),
    ("POST", "/api/v1/schedules"),
    ("PUT", "/api/v1/schedules/sched-1"),
    ("DELETE", "/api/v1/schedules/sched-1"),
    ("POST", "/api/v1/sites"),
    ("PUT", "/api/v1/sites/site-1"),
    ("DELETE", "/api/v1/sites/site-1"),
    ("GET", "/pgweb"),
    ("GET", "/pgweb/"),
    ("GET", "/api/v1/workflows"),
]


class Upstream(BaseHTTPRequestHandler):
    hits: list[tuple[str, str]] = []
    lock = threading.Lock()

    def log_message(self, fmt: str, *args) -> None:
        return

    def _do(self) -> None:
        path = self.path.split("?", 1)[0]
        with self.lock:
            self.hits.append((self.command, path))
        body = b"UPSTREAM"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body) if self.command != "HEAD" else 0))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_HEAD = do_PUT = do_PATCH = do_DELETE = _do


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def basic(password: str) -> str:
    token = base64.b64encode(f"{USER}:{password}".encode()).decode()
    return f"Basic {token}"


def fetch(base: str, method: str, path: str, password: str | None = None, authorization: str | None = None):
    req = urllib.request.Request(base + path, data=b"{}" if method in {"POST", "PUT", "PATCH"} else None, method=method)
    if authorization:
        req.add_header("Authorization", authorization)
    elif password is not None:
        req.add_header("Authorization", basic(password))
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.headers, res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def challenge(headers) -> str:
    return headers.get("WWW-Authenticate") or ""


def wait_until(pred, what: str, seconds: float = 8) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.05)
    raise SystemExit(f"timed out waiting for {what}")


def adapt(caddy: str, config: Path, env: dict) -> dict:
    proc = subprocess.run(
        [caddy, "adapt", "--adapter", "caddyfile", "--config", str(config)],
        check=False, capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        raise SystemExit(f"caddy adapt {config.name} failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def has_auth(node) -> bool:
    if isinstance(node, dict):
        if node.get("handler") == "authentication":
            return True
        return any(has_auth(v) for v in node.values())
    if isinstance(node, list):
        return any(has_auth(v) for v in node)
    return False


def routes_of(cfg: dict, listen_prefix: str | None = None) -> list:
    servers = cfg["apps"]["http"]["servers"]
    if listen_prefix is None:
        return next(iter(servers.values()))["routes"]
    for server in servers.values():
        if any(str(a).endswith(listen_prefix) or listen_prefix in str(a) for a in server.get("listen", [])):
            return server["routes"]
    raise SystemExit(f"no server listening on {listen_prefix} in {list(servers)}")


def path_routes(routes: list) -> list[tuple[list, bool]]:
    out = []
    for route in routes:
        paths: list[str] = []
        for match in route.get("match") or []:
            paths.extend(match.get("path") or [])
        out.append((paths, has_auth(route)))
    return out


def assert_same_policy(a: list[tuple[list, bool]], b: list[tuple[list, bool]], label: str) -> None:
    if a != b:
        raise SystemExit(f"{label} route policy differs from the plain-HTTP front door")


def write_auth(path: Path, caddy: str) -> None:
    proc = subprocess.run(
        [caddy, "hash-password", "--plaintext", PASSWORD, "--bcrypt-cost", "4"],
        check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr)
    path.write_text(f"{USER} {proc.stdout.strip()}\n")


def stage_configs(tmp: Path) -> None:
    for name in ("Caddyfile", "Caddyfile.tls", "Caddyfile.tls.pgweb", "routes.caddy", "pgweb.caddy"):
        shutil.copy(ROOT / name, tmp / name)
    certs = tmp / "certs"
    certs.mkdir()
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-keyout", str(certs / "server.key"), "-out", str(certs / "server.crt"),
         "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    for name in ("Caddyfile.tls", "Caddyfile.tls.pgweb"):
        file = tmp / name
        file.write_text(file.read_text().replace("/certs/server.crt", str(certs / "server.crt"))
                        .replace("/certs/server.key", str(certs / "server.key")))


def check_static_configs(caddy: str, tmp: Path) -> None:
    env = os.environ.copy()
    env.update({
        "LAN_IP": "127.0.0.1", "NF_UPSTREAM": "127.0.0.1:9", "NF_PORT": "18099",
        "TLS_PORT": "18443", "CADDY_ACCESS_LOG": str(tmp / "access.log"),
    })
    plain = adapt(caddy, tmp / "Caddyfile", {**env, "APP_ID": "open-fdd"})
    lite = adapt(caddy, tmp / "Caddyfile", {**env, "APP_ID": "open-fdd-lite"})
    tls = adapt(caddy, tmp / "Caddyfile.tls", env)
    pg = adapt(caddy, tmp / "Caddyfile.tls.pgweb", env)

    def redir(cfg: dict) -> str:
        for server in cfg["apps"]["http"]["servers"].values():
            if any(str(a).endswith(":80") for a in server.get("listen", [])):
                return json.dumps(server)
        raise SystemExit("plain HTTP config has no :80 listener")

    full_redir, lite_redir = redir(plain), redir(lite)
    if "/api/v1/apps/static/open-fdd/" not in full_redir:
        raise SystemExit("Full :80 redirect does not open the open-fdd dashboard")
    if "/api/v1/apps/static/open-fdd-lite/" not in lite_redir:
        raise SystemExit("Lite :80 redirect does not open the open-fdd-lite dashboard")
    if "basic_auth" in full_redir or "authentication" in full_redir:
        raise SystemExit("the :80 redirect listener must not ask for a login")

    plain_routes = path_routes(routes_of(plain, ":18099"))
    assert_same_policy(plain_routes, path_routes(routes_of(lite, ":18099")), "Lite")
    assert_same_policy(plain_routes, path_routes(routes_of(tls, ":18443")), "HTTPS")

    pg_routes = path_routes(routes_of(pg, ":18443"))
    pg_hits = [(paths, auth) for paths, auth in pg_routes if any(p.startswith("/pgweb") for p in paths)]
    if pg_hits != [(["/pgweb", "/pgweb/*"], True)]:
        raise SystemExit(f"pgweb must stay behind basic auth, got {pg_hits}")
    if any(any(p.startswith("/pgweb") for p in paths) for paths, _auth in plain_routes):
        raise SystemExit("default routes expose pgweb")


def main() -> None:
    if not Path(CADDY).is_file():
        raise SystemExit(f"caddy binary not found ({CADDY})")
    failures: list[str] = []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            failures.append(msg)

    with tempfile.TemporaryDirectory(prefix="caddy-routes-") as raw:
        tmp = Path(raw)
        stage_configs(tmp)
        write_auth(tmp / "auth.caddy", CADDY)
        check_static_configs(CADDY, tmp)

        upstream_port = free_port()
        server = ThreadingHTTPServer(("127.0.0.1", upstream_port), Upstream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        front = free_port()
        live = tmp / "Caddyfile.live"
        live.write_text(
            "{\n\tauto_https off\n\tadmin off\n}\n"
            f":{front} {{\n\tbind 127.0.0.1\n\timport routes.caddy\n}}\n"
        )
        log = tmp / "live.log"
        proc = subprocess.Popen(
            [CADDY, "run", "--config", str(live), "--adapter", "caddyfile"],
            cwd=tmp,
            env={**os.environ, "NF_UPSTREAM": f"127.0.0.1:{upstream_port}", "CADDY_ACCESS_LOG": str(log)},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        base = f"http://127.0.0.1:{front}"
        try:
            def up() -> bool:
                if proc.poll() is not None:
                    raise SystemExit(f"caddy exited\n{proc.stdout.read() if proc.stdout else ''}")
                try:
                    fetch(base, "GET", "/favicon.ico")
                    return True
                except OSError:
                    return False
            wait_until(up, "caddy")

            def seen(method: str, path: str) -> bool:
                bare = path.split("?", 1)[0]
                with Upstream.lock:
                    return (method, bare) in Upstream.hits

            def reset() -> None:
                with Upstream.lock:
                    Upstream.hits.clear()

            for method, path in PUBLIC:
                reset()
                status, headers, body = fetch(base, method, path)
                check(status == 200, f"public {method} {path} -> {status}")
                check(not challenge(headers), f"public {method} {path} sent a login challenge")
                check(seen(method, path), f"public {method} {path} did not reach upstream")
                if method != "HEAD":
                    check(body == b"UPSTREAM", f"public {method} {path} body was not the upstream")

            for method, path in QUIET:
                reset()
                status, headers, body = fetch(base, method, path)
                check(status == 403, f"quiet {method} {path} -> {status}, want 403")
                check(not challenge(headers), f"quiet {method} {path} popped a login challenge")
                check(not seen(method, path), f"quiet {method} {path} reached upstream with no login")
                check(b"UPSTREAM" not in body, f"quiet {method} {path} returned upstream bytes")
                reset()
                status, headers, body = fetch(base, method, path, PASSWORD)
                check(status == 200 and seen(method, path), f"quiet {method} {path} rejected a valid login ({status})")
                check(not challenge(headers), f"quiet {method} {path} challenged a valid login")
                reset()
                status, headers, _body = fetch(base, method, path, PASSWORD + "-no")
                check(status == 401 and "basic" in challenge(headers).lower() and not seen(method, path),
                      f"quiet {method} {path} did not reject a bad login ({status} {challenge(headers)!r})")

            for method, path in PROTECTED:
                reset()
                status, headers, body = fetch(base, method, path)
                chal = challenge(headers)
                check(status == 401, f"protected {method} {path} -> {status}, want 401")
                check("basic" in chal.lower() and "restricted" in chal.lower(),
                      f"protected {method} {path} challenge was {chal!r}")
                check(not seen(method, path) and b"UPSTREAM" not in body,
                      f"protected {method} {path} was proxied after a cancelled login")

            # A valid login reaches the console and a write. Cancelling (above) does not.
            for method, path in (("GET", "/"), ("POST", "/api/v1/bacnet/local"), ("GET", "/api/v1/apps/open-fdd")):
                reset()
                status, _headers, body = fetch(base, method, path, PASSWORD)
                check(status == 200 and body == b"UPSTREAM" and seen(method, path),
                      f"valid login did not reach {method} {path} ({status})")

            # A non-basic credential must not open the app listing.
            reset()
            status, headers, _body = fetch(base, "GET", "/api/v1/apps", authorization="Bearer not-a-password")
            check(status == 401 and "basic" in challenge(headers).lower() and not seen("GET", "/api/v1/apps"),
                  f"bearer token opened or hid GET /api/v1/apps ({status})")

            # Dot segments collapse before the match, so a public prefix cannot reach a locked path.
            for method, path in (("GET", "/api/v1/sites/../apps"), ("GET", "/api/v1/apps/static/../apps"),
                                 ("POST", "/API/v1/bacnet/local")):
                reset()
                status, _headers, body = fetch(base, method, path)
                check(status in {401, 403} and b"UPSTREAM" not in body and not Upstream.hits,
                      f"normalized {method} {path} was proxied ({status})")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            server.shutdown()

    if failures:
        raise SystemExit("route matrix failed:\n- " + "\n- ".join(failures))
    print(f"route matrix ok: {len(PUBLIC)} public, {len(QUIET)} no-challenge, {len(PROTECTED)} basic-auth")


if __name__ == "__main__":
    main()
