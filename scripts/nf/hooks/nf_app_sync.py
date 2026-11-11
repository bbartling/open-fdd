#!/usr/bin/env python3
"""Sync an NF Applications SDK app between open-fdd (source of truth) and an NF box.

The app is described by a manifest next to the hook source, e.g.
``nf-app/app.json`` or ``lite/app.json``: the application (id, runtime,
auth scopes), a map of NF file path -> repo file, the hook definitions
(UpdateHook bodies) and an optional top-level ``replaces`` list (ids of
predecessor apps that ``install --remove-old`` may delete). Talks to the NF
*local console* API with HTTP Basic auth (the remote portal API-key token is
read-only and cannot deploy).

    # credentials: CONSOLE_USERNAME / CONSOLE_PASSWORD, NF_CONSOLE_URL (optional NF_CA_FILE)
    ENV=~/.secrets/nf_site_console.env
    M=nf-app/app.json
    S=scripts/nf/hooks/nf_app_sync.py

    # one command (preflight -> push -> npm dependencies -> verify):
    python3 $S --env $ENV install $M
    python3 $S --env $ENV install $M --remove-old          # also LIST the predecessor apps / orphan points
    python3 $S --env $ENV install $M --remove-old --yes    # ... and delete the predecessor apps
    python3 $S --env $ENV uninstall $M [--yes]             # dry run unless --yes
    python3 $S --env $ENV doctor $M                        # read-only pass/fail checks

    # the pieces:
    python3 $S --env $ENV status $M
    python3 $S --env $ENV push   $M [--skip-hooks] [--skip-deps] [--hook fdd]
    python3 $S --env $ENV run    $M                      # scheduled hooks (+ on-request hooks given --arg)
    python3 $S --env $ENV run    $M --hook sparql --arg query='SELECT * WHERE {?s ?p ?o} LIMIT 1'
    python3 $S --env $ENV run    $M --hook fdd --wait 900 | --resume 12345
    python3 $S --env $ENV pull   $M | diff $M

    # hand-edited files on the box: push/install STOP and list them (exit 4, nothing written) unless
    python3 $S --env $ENV install $M --save-remote ./box-copies   # download the edited box copies first (then it still stops)
    python3 $S --env $ENV install $M --force                      # overwrite them

Dependencies: NF installs an app's ``package.json`` with ``PATCH /api/v1/apps/<id>/dependencies`` (then the
runtimes restart). ``push`` does that after writing ``package.json`` and before the hooks are (re)started;
``--skip-deps`` leaves it out. sql.js is vendored, so the sqlite engine needs no npm install.

TLS to a self-signed front door: ``--ca-file FILE`` (or NF_CA_FILE) trusts that certificate; ``--pin-server-cert``
fetches the leaf the server presents, prints its SHA-256 fingerprint and trusts only that one for this process
(its SAN must match the host). Verification is never turned off.

``run`` does not touch the schedule. It waits for each run up to the hook's ``invokeTimeout`` + 60 s
(``--wait SECONDS`` overrides). If the wait runs out the run is reported as still running with its pid
and the exit status is 3 (1 = a run failed, including a hook that returns ``ok: false``); the hook is never
started a second time: use ``--resume PID``. Installer guard: every push records the sha256 of each file it wrote in ``static/version.json`` (``files``). The next
push / install compares the box with that manifest first and STOPS (exit 4, nothing written) when a file was edited by
hand on the box; an older install without a manifest is compared with the installed commit's copy (or this repo's).
``--save-remote DIR`` downloads the edited box copies for review, ``--force`` overwrites them, ``doctor`` lists them
(read-only). Text files are uploaded with LF line endings whatever core.autocrlf is.

Never prints passwords or the app's API client secret
(GetApplications returns it; this script drops it).
"""

from __future__ import annotations

import argparse
import atexit
import base64
import datetime
import difflib
import errno
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import subprocess
import socket
import ssl
import sys
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # scripts/nf: the shared point/query pager
from nf_paging import PagingError, page_all  # noqa: E402

UA = "openfdd-nf-app-sync/1.0"

ON_REQUEST = "MODE_ON_REQUEST"
INSTALLED = "STATUS_INSTALLED"
NEEDS_CONSOLE = ("deploy needs the NF local console: set NF_CONSOLE_URL and CONSOLE_USERNAME / CONSOLE_PASSWORD "
                 "(the Normal Online portal API key NF_CLIENT_ID / NF_CLIENT_SECRET is read-only and cannot deploy)")


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def env_problem(env: dict[str, str], where: str = "the env file") -> str | None:
    """A short message when `env` cannot deploy (no console login), else None. Names variables, never values."""
    if env.get("CONSOLE_USERNAME") and env.get("CONSOLE_PASSWORD"):
        if env.get("NF_CONSOLE_URL"):
            return None
        return f"NF_CONSOLE_URL missing from {where} (or pass --console)"
    if env.get("NF_CLIENT_ID") or env.get("NF_CLIENT_SECRET"):
        return (f"{where} holds a portal API key (NF_CLIENT_ID / NF_CLIENT_SECRET) and no console login; "
                + NEEDS_CONSOLE)
    return f"CONSOLE_USERNAME / CONSOLE_PASSWORD missing from {where}; " + NEEDS_CONSOLE


def auth_layer(www_authenticate: str | None) -> str:
    """Which layer sent a 401, from its WWW-Authenticate realm: Caddy's front door or NF itself."""
    m = re.search(r'realm="([^"]*)"', www_authenticate or "", re.I)
    realm = m.group(1) if m else None
    if realm is None:
        return "an unknown layer (no WWW-Authenticate realm)"
    if realm.lower() == "restricted":
        return 'the Caddy front door (realm="restricted"): its basic_auth user/password hash did not accept this login'
    if realm.lower().startswith("nf-"):
        return f'NF itself (realm="{realm}"): the console login (CONSOLE_USERNAME / CONSOLE_PASSWORD in NF\'s env) did not accept it'
    return f'a layer with realm="{realm}"'


class ApiError(SystemExit):
    """A failed console call; the message is the exit text, `status` the HTTP status (0 = not HTTP).

    `kind` says what failed: "connectivity" (no HTTP response at all), "tls" (certificate trust / hostname),
    "auth" (a real HTTP 401/403), "http" (any other HTTP error) or "" (not classified).

    `nf_missing_file` is set when the response matches NF's missing-app-file signature (HTTP 500,
    Content-Type application/grpc, empty body) observed on NF 3.10.x; the body is never copied into
    the message. Callers decide whether that signature may be treated as missing for a given path.
    """

    def __init__(self, msg: str, status: int = 0, kind: str = ""):
        super().__init__(msg)
        self.status = status
        self.kind = kind
        self.nf_missing_file = False




def is_nf_missing_file_response(status: int, content_type: str | None, body: bytes | None) -> bool:
    """True when an app-file GET looks like NF 3.10.x "not found" rather than a real server fault.

    Observed on a live console: missing paths return HTTP 500, Content-Type application/grpc, and an
    empty body (no JSON). Existing files return HTTP 200 with application/json. Match on these
    fields only; never put the body into an error message (it may contain credentials on other 500s).
    """
    if status != 500:
        return False
    if body:  # any payload is treated as a real error page / fault
        return False
    ct = (content_type or "").split(";")[0].strip().lower()
    return ct == "application/grpc"


def remote_file_paths(c, app_id: str) -> set[str] | None:
    """Paths listed on the installed app (`files[].path` from GET /api/v1/apps), or None if unknown.

    A present `files` list (even empty) is authoritative: a path absent from it is not on the box.
    When the field is missing, callers must fall back to GET / not-found signature handling.
    """
    app = c.app(app_id) if hasattr(c, "app") else None
    if not isinstance(app, dict) or "files" not in app:
        return None
    files = app.get("files")
    if not isinstance(files, list):
        return None
    return {f["path"] for f in files if isinstance(f, dict) and f.get("path")}


def path_is_new_on_box(nf_path: str, known_paths: set[str] | None, push_manifest: dict | None) -> bool:
    """Return whether a path is provably new to the installed app.

    The app file listing is authoritative when available: an absent path is new, while a listed
    path is existing even if it is absent from the push manifest. Only when the listing is
    unavailable is the last-push manifest used. If both sources are unavailable, the path is not
    considered new, so an ambiguous HTTP 500 remains an error.

    Args:
        nf_path: Absolute NF app-file path, such as ``/hooks/lib/example.js``.
        known_paths: Paths returned by NF's app listing, or ``None`` if unavailable.
        push_manifest: File map from the last push, or ``None`` if unavailable.
    """
    if known_paths is not None and nf_path not in known_paths:
        return True
    if known_paths is None and push_manifest is not None and nf_path not in push_manifest:
        return True
    return False

FRONT_DOOR_HINT = ("if NF is behind a front door (Caddy), use the front door URL (e.g. https://host), not NF's own "
                   "port; NF may listen on loopback only")


def safe_origin(base: str) -> str:
    """scheme://host:port only: never userinfo, path, query or fragment."""
    try:
        u = urllib.parse.urlparse(base)
        host = u.hostname or "?"
        if ":" in host:
            host = f"[{host}]"
        port = u.port or {"http": 80, "https": 443}.get(u.scheme)
    except ValueError:
        return "(unparseable console URL)"
    return f"{u.scheme or '?'}://{host}" + (f":{port}" if port else "")


def classify_transport(exc: BaseException, connecting: bool = True) -> tuple[str, str]:
    """(kind, label) for an exception raised with no HTTP response: kind is "tls" or "connectivity".

    The label is a fixed phrase, never the exception text, so URLs or credentials nested in it cannot leak.
    `connecting` False means the connection was made and the wait for the reply failed (read timeout)."""
    reason = getattr(exc, "reason", exc) if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        text = f"{getattr(reason, 'verify_message', '')} {reason}".lower()
        if getattr(reason, "verify_code", None) in (62, 64) or "hostname" in text or "mismatch" in text \
                or "doesn't match" in text:
            return "tls", "TLS certificate does not match the host name"
        return "tls", "TLS certificate not trusted"
    if isinstance(reason, ssl.SSLError):
        return "tls", "TLS handshake failed"
    if isinstance(reason, TimeoutError):  # socket.timeout is TimeoutError on 3.10+
        return "connectivity", "connect timed out" if connecting else "read timed out (connected, no reply)"
    if isinstance(reason, ConnectionRefusedError):
        return "connectivity", "connection refused"
    if isinstance(reason, socket.gaierror):
        return "connectivity", "DNS lookup failed"
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, http.client.HTTPException)):
        return "connectivity", "connection dropped before a complete reply"
    if isinstance(reason, OSError) and (reason.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, 10051, 10065)
                                        or getattr(reason, "winerror", None) in (10051, 10065)):
        return "connectivity", "network or host unreachable"
    return "connectivity", f"transport error ({type(reason).__name__})"


def transport_error(method: str, path: str, base: str, exc: BaseException, connecting: bool = True) -> ApiError:
    """The ApiError for a request that got no HTTP response. Read-only text: scheme/host/port and path only."""
    kind, label = classify_transport(exc, connecting)
    where = f"{method} {path.split('?')[0]}"
    origin = safe_origin(base)
    if kind == "tls":
        return ApiError(f"{where}: {label} at {origin}; trust the server certificate with --ca-file / NF_CA_FILE or "
                        "--pin-server-cert (verification is never disabled)", 0, "tls")
    return ApiError(f"{where}: {label} at {origin}, before any login was attempted; credentials were not validated. "
                    f"Check the configured console URL (NF_CONSOLE_URL / --console), the listener and the network path "
                    f"or VPN/port-forward; {FRONT_DOOR_HINT}.", 0, "connectivity")


def make_ssl_context(ca_file: str | None = None) -> ssl.SSLContext | None:
    """Default verification plus (optionally) one extra trusted certificate file. Never disables verification."""
    if not ca_file:
        return None
    p = Path(ca_file).expanduser()
    if not p.is_file():
        raise SystemExit(f"CA file not found: {p}")
    return ssl.create_default_context(cafile=str(p))


def pin_server_cert(base: str, timeout: float = 10.0, fetch=ssl.get_server_certificate):
    """Fetch the leaf certificate `base` presents, trust only it for this process and check that its SAN names the
    host. Returns (ssl_context, sha256_fingerprint). The PEM lives in a temp file removed at exit."""
    u = urllib.parse.urlparse(base)
    if u.scheme != "https" or not u.hostname:
        raise SystemExit("--pin-server-cert needs an https:// console URL")
    host, port = u.hostname, u.port or 443
    try:
        pem = fetch((host, port), timeout=timeout)
    except OSError as e:
        raise SystemExit(f"could not fetch the server certificate from {host}:{port}: {e}") from None
    fp = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    fd, name = tempfile.mkstemp(suffix=".pem", prefix="nf-pin-")
    with os.fdopen(fd, "w") as f:
        f.write(pem)
    atexit.register(lambda: Path(name).unlink(missing_ok=True))
    ctx = ssl.create_default_context(cafile=name)  # check_hostname stays on: the SAN must name the host
    try:
        with socket.create_connection((host, port), timeout=timeout) as s, ctx.wrap_socket(s, server_hostname=host):
            pass
    except ssl.SSLCertVerificationError as e:
        raise SystemExit(f"the certificate {host}:{port} presents does not match the host ({e.verify_message}); "
                         "not trusting it") from None
    except OSError as e:
        raise SystemExit(f"could not verify the pinned certificate at {host}:{port}: {e}") from None
    return ctx, fp


class Console:
    def __init__(self, base: str, user: str, password: str, ctx: ssl.SSLContext | None = None):
        self.base = base.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.ctx = ctx

    def call(self, method: str, path: str, body=None, ok_404: bool = False):
        data = None if body is None else json.dumps(body).encode()
        shown = path.split("?")[0]  # messages never carry a query string
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": self.auth, "User-Agent": UA, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120, context=self.ctx) as r:
                text = r.read().decode()
        except urllib.error.HTTPError as e:
            # Drain the body for signature matching, but never put it in the message: error pages /
            # reverse proxies can echo Authorization headers or other secrets (#1554 CodeRabbit Major).
            raw = b""
            try:
                raw = e.read() or b""
            except OSError:
                raw = b""
            hdrs = e.headers if e.headers is not None else {}
            ctype = ""
            if hasattr(hdrs, "get"):
                ctype = hdrs.get("Content-Type") or hdrs.get("content-type") or ""
            elif isinstance(hdrs, dict):
                ctype = hdrs.get("Content-Type") or hdrs.get("content-type") or ""
            if ok_404 and e.code == 404:
                return None  # classic missing file
            if e.code == 401:
                raise ApiError(f"{method} {shown} -> HTTP 401: rejected by {auth_layer(hdrs.get('WWW-Authenticate') if hasattr(hdrs, 'get') else None)}. "
                               + NEEDS_CONSOLE + ". Caddy and NF must accept the same user and password.",
                               401, "auth") from None
            if e.code == 403:
                raise ApiError(f"{method} {shown} -> HTTP 403: forbidden by {auth_layer(hdrs.get('WWW-Authenticate') if hasattr(hdrs, 'get') else None)}. "
                               "The server answered, so the URL is reachable, but this login is not permitted to do this "
                               "(check the user's role / API scopes). " + NEEDS_CONSOLE, 403, "auth") from None
            err = ApiError(f"{method} {shown} -> HTTP {e.code}", e.code, "http")
            # Flag NF's missing-file 500 signature for callers; do not treat it as missing here.
            err.nf_missing_file = is_nf_missing_file_response(e.code, ctype, raw)
            raise err from None
        except (OSError, http.client.HTTPException) as e:  # URLError, ssl errors, timeouts, resets
            connecting = isinstance(e, urllib.error.URLError)  # a bare timeout is raised while reading the reply
            raise transport_error(method, path, self.base, e, connecting) from None
        if text.lstrip().startswith("<"):
            raise ApiError(f"{method} {shown} returned HTML, not the NF API. NF_CONSOLE_URL (or --console) may point at "
                           "the app front door / static UI instead of the NF console: try the NF console port, or the "
                           "front-door route that proxies the NF API. (Rarely: this NF version has no such route.)", 0)
        return json.loads(text) if text else {}

    def probe(self, path: str) -> tuple[int, dict[str, str]]:
        """Unauthenticated GET that does not follow redirects: (status, headers). Status 0 = unreachable."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        handlers: list = [NoRedirect()]
        if self.ctx is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self.ctx))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(urllib.request.Request(self.base + path, headers={"User-Agent": UA}), timeout=20) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)
        except (OSError, ssl.SSLError):
            return 0, {}

    def apps(self) -> list[dict]:
        out = []
        for a in self.call("GET", "/api/v1/apps").get("applications", []):
            a.pop("auth", None)  # contains the generated client secret
            out.append(a)
        return out

    def app(self, app_id: str):
        return next((a for a in self.apps() if a.get("id") == app_id), None)

    def read_file(self, app_id: str, nf_path: str, *, known_paths: set[str] | None = None,
                  push_manifest: dict | None = None) -> bytes | None:
        """Read an NF app file as bytes, returning ``None`` only for a confirmed absence.

        A path absent from a supplied ``known_paths`` listing is not requested. A successful
        404 is missing; NF 3.10 may instead return HTTP 500 with ``application/grpc`` and an
        empty body for a missing file. That signature is accepted only when
        ``path_is_new_on_box`` can prove the path is new. Listed/existing paths and all other
        HTTP 500 responses raise ``ApiError`` so callers stop before writing.

        Args:
            app_id: NF application id.
            nf_path: Absolute path to the app file on NF.
            known_paths: App-listing paths, or ``None`` when the listing is unavailable.
            push_manifest: Last-push file map used only when ``known_paths`` is unavailable.
        """
        if known_paths is not None and nf_path not in known_paths:
            return None
        try:
            r = self.call("GET", f"/api/v1/apps/{app_id}/files{nf_path}", ok_404=True)
        except ApiError as e:
            if getattr(e, "nf_missing_file", False) and path_is_new_on_box(nf_path, known_paths, push_manifest):
                return None
            raise
        return None if r is None else base64.b64decode(r.get("data", ""))


# Local script/stylesheet references in HTML ("app.js", "style.css"), not URLs or absolute paths.
ASSET_REF = re.compile(r'(?<![\w-])(src|href)="(?![a-z][a-z0-9+.-]*:|/|#)([^"?#]+\.(?:js|mjs|css))"')
STAMP = re.compile(r'(\.(?:js|mjs|css))\?v=[0-9a-f]{10}"')


TEXT_SUFFIXES = (".js", ".mjs", ".json", ".css", ".html", ".sql", ".md", ".txt", ".svg")


def lf_bytes(rel: str, data: bytes) -> bytes:
    """Text files go to the box with LF line endings whatever the checkout's core.autocrlf (a Windows checkout would
    otherwise upload CRLF files, +1 byte per line, and every box copy would differ from the git blob). Binary
    files (.wasm, ...) are untouched."""
    name = rel.rsplit("/", 1)[-1].lower()
    if name.endswith(TEXT_SUFFIXES) or name.startswith("license"):
        return data.replace(b"\r\n", b"\n")
    return data


def deploy_bytes(m: dict, rel: str) -> bytes:
    """File bytes as deployed (LF line endings for text files). HTML gets each local asset reference stamped with
    the asset's content hash (app.js -> app.js?v=<sha256[:10]>): NF serves app files with a 5-minute cache,
    so a changed file needs a new URL or browsers mix old and new files after a deploy."""
    path = m["_dir"] / rel
    data = lf_bytes(rel, path.read_bytes())
    if not rel.endswith(".html"):
        return data

    def stamp(mo: re.Match) -> str:
        asset = path.parent / mo.group(2)
        if not asset.is_file():
            return mo.group(0)
        digest = hashlib.sha256(lf_bytes(mo.group(2), asset.read_bytes())).hexdigest()[:10]
        return f'{mo.group(1)}="{mo.group(2)}?v={digest}"'

    return ASSET_REF.sub(stamp, data.decode("utf-8")).encode("utf-8")


def strip_stamps(data: bytes) -> bytes:
    """Undo deploy_bytes() stamping so pulled HTML matches the repo form."""
    return STAMP.sub(r'\1"', data.decode("utf-8", errors="replace")).encode("utf-8")


def manifest(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))
    m["_dir"] = path.parent
    return m


def option_value(app: dict | None, name: str):
    """The string value of an app option (e.g. "version"), or None."""
    for o in (app or {}).get("options", []):
        if o.get("name") == name:
            return (o.get("value") or {}).get("string")
    return None


def cmd_status(c: Console, m: dict) -> int:
    app_id = m["application"]["id"]
    a = c.app(app_id)
    if not a:
        print(f"app {app_id}: not installed")
        return 1
    installed = option_value(a, "version")
    print(f"app {app_id}: {a.get('status')} version={installed or 'unknown'}")
    print(f"  files={[f['path'] for f in a.get('files', [])]}")
    for h in a.get("hooks", []):
        rt = c.call("GET", f"/api/v1/apps/{app_id}/hooks/{h['id']}/runtimes")
        runs = c.call("GET", f"/api/v1/apps/{app_id}/hooks/{h['id']}/runs?page_size=5&include_results=true")
        print(f"hook {h['id']}: mode={h.get('mode')} status={h.get('status')} "
              f"schedule={h.get('schedule', {}).get('rrule', '').replace(chr(10), ' ')} "
              f"scheduler_last_run={rt.get('scheduler', {}).get('lastRun')}")
        for r in runs.get("runs", []):
            print(f"  run pid={r.get('pid')} {r.get('trigger')} {r.get('state')} start={r.get('startTime')}")
    return 0


def version_info(start: Path) -> dict:
    """{version, commit, dirty, deployed} for the app's static/version.json: the repo's VERSION
    file (searched upward from the manifest) and the git commit the files come from."""
    root = next((d for d in [start.resolve(), *start.resolve().parents] if (d / "VERSION").is_file()), None)
    version = (root / "VERSION").read_text(encoding="utf-8").strip() if root else "0.0.0"

    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=root or start, capture_output=True, text=True,
                                  timeout=20, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    return {"version": version, "commit": commit, "dirty": dirty,
            "deployed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def app_slug(name: str) -> str:
    """NF 3.10 derives an app's id from its name (lower case, non-alphanumerics -> "-");
    the id sent in CreateApplication is ignored."""
    return "-".join(re.findall(r"[a-z0-9]+", name.lower()))


# ---------------------------------------------------------------- npm dependencies

DEPS_SETTLE_SECONDS = 300.0   # wait for the app to be installed again after the dependencies call
DEPS_PROBE_SECONDS = 30.0     # then wait this long for the packages to show up in the app's files


def declared_deps(m: dict) -> list[str]:
    """Package names in the app's package.json dependencies (the manifest's /package.json file), [] if none."""
    rel = (m.get("files") or {}).get("/package.json")
    if not rel or not (m["_dir"] / rel).is_file():
        return []
    try:
        return sorted(json.loads((m["_dir"] / rel).read_text(encoding="utf-8")).get("dependencies") or {})
    except ValueError:
        return []


def deps_present(c, app_id: str, names: list[str]) -> list[str]:
    """Which of `names` the app's file API shows as installed (node_modules/<name>/package.json). A box whose
    file API does not expose node_modules shows none: absence here is "not confirmed", not "missing"."""
    return [n for n in names if c.read_file(app_id, f"/node_modules/{n}/package.json") is not None]


def install_deps(c, m: dict, clock=time.monotonic, sleep=time.sleep,
                 settle: float = DEPS_SETTLE_SECONDS, probe: float = DEPS_PROBE_SECONDS) -> dict:
    """Install the app's package.json dependencies (PATCH /api/v1/apps/<id>/dependencies) and wait until the app is
    installed again. Returns {"requested", "names", "present", "confirmed", "error"}. Never raises: a NF without the
    route is reported (error) and the caller decides. The hook runtimes are restarted by the caller afterwards."""
    app_id = m["application"]["id"]
    names = declared_deps(m)
    out = {"requested": False, "names": names, "present": [], "confirmed": False, "error": None}
    if not names:
        out["confirmed"] = True
        return out
    try:
        c.call("PATCH", f"/api/v1/apps/{app_id}/dependencies", {})
    except SystemExit as e:
        out["error"] = str(e)
        return out
    out["requested"] = True
    deadline = clock() + settle
    while clock() < deadline:   # the install may run asynchronously: wait for the app to settle
        a = c.app(app_id)
        if not a or a.get("status") in (None, "", INSTALLED):
            break
        sleep(POLL_SECONDS)
    deadline = clock() + probe
    while True:
        out["present"] = deps_present(c, app_id, names)
        if len(out["present"]) == len(names):
            out["confirmed"] = True
            break
        if clock() >= deadline:
            break
        sleep(POLL_SECONDS)
    return out


def manual_deps_hint(app_id: str) -> str:
    return (f"install them by hand: PATCH /api/v1/apps/{app_id}/dependencies (body {{}}) with the console login, "
            f"then PATCH /api/v1/apps/{app_id}/restart; or set the fdd hook engine to \"sqlite\"")


def report_deps(res: dict, app_id: str) -> None:
    if not res["names"]:
        print("dependencies: none declared")
    elif res["error"]:
        print(f"dependencies: NOT installed ({res['error']}). {manual_deps_hint(app_id)}")
    elif res["confirmed"]:
        print(f"dependencies: installed ({', '.join(res['names'])})")
    else:
        print(f"dependencies: install requested; files not visible through the file API "
              f"(seen {len(res['present'])}/{len(res['names'])}). The first hook run below confirms them")


# ---------------------------------------------------------------- installer guard: hand-edited files on the box

EXIT_DRIFT = 4          # push/install stopped: files on the box were edited by hand (nothing was written)
PUSH_MANIFEST_KEY = "files"   # static/version.json -> {"files": {"/hooks/x.js": sha256, ...}}: what the last push wrote


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote_version_info(c, app_id: str, known_paths: set[str] | None = None) -> dict:
    """The box's static/version.json as a dict ({} when absent).

    Missing (404, absent from the app file list, or NF's missing-file 500 signature for a new
    path) -> {}. Other read errors (unrelated HTTP 500, etc.) propagate so the push guard stops
    with the real error instead of falling back to the repo baseline and then reporting unrelated
    files as hand-edited.
    """
    raw = c.read_file(app_id, "/static/version.json", known_paths=known_paths)
    if not raw:
        return {}
    try:
        info = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError):
        return {}
    return info if isinstance(info, dict) else {}


def commit_blob(m: dict, rel: str, commit: str) -> bytes | None:
    """The repo file `rel` as it was in `commit` (git show), LF-normalized; None when git or the commit is not available."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit or ""):
        return None
    try:
        path = (m["_dir"] / rel).resolve()
        root = next((d for d in [path.parent, *path.parents] if (d / "VERSION").is_file()), None)
        if root is None:
            return None
        out = subprocess.run(["git", "show", f"{commit}:{path.relative_to(root).as_posix()}"], cwd=root,
                             capture_output=True, timeout=30, check=True).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return lf_bytes(rel, out)


def find_drift(c, m: dict, only: set[str] | None = None) -> dict:
    """Which files on the box were edited by hand since the last push. Read-only. `only` limits the check to those NF
    paths (the schema-probe bootstrap guards just the files it will write).

    Baseline, best first:
      "manifest"  the sha256 of every file the last push wrote (static/version.json "files"): the exact answer;
      "commit"    no manifest (an older install): the same file in the git commit version.json names, when this
                  checkout has it;
      "repo"      neither: this repo's copy of the same file.
    A file the push would write byte for byte is never drift (nothing would be lost). Returns
    {"baseline", "commit", "drifted": [nf_path], "remote": {nf_path: bytes}, "checked": n}; no app = nothing to lose.

    Files absent from the installed app's `files` list (or answered with NF's missing-file HTTP 500
    signature when the path is new relative to the box) are skipped: nothing to lose. Unrelated HTTP
    500 responses still abort the guard.
    """
    app_id = m["application"]["id"]
    out = {"baseline": "none", "commit": "", "drifted": [], "remote": {}, "checked": 0}
    if not c.app(app_id):
        return out
    known = remote_file_paths(c, app_id)
    info = remote_version_info(c, app_id, known_paths=known)
    pushed = info.get(PUSH_MANIFEST_KEY) if isinstance(info.get(PUSH_MANIFEST_KEY), dict) else None
    commit = str(info.get("commit") or "")
    out["baseline"] = "manifest" if pushed is not None else "commit" if commit else "repo"
    out["commit"] = commit
    for nf_path, rel in m["files"].items():
        if only is not None and nf_path not in only:
            continue
        remote = c.read_file(app_id, nf_path, known_paths=known, push_manifest=pushed)
        if remote is None:
            continue                       # not on the box yet: nothing to lose
        out["checked"] += 1
        local = deploy_bytes(m, rel) if (m["_dir"] / rel).is_file() else b""
        if remote == local:
            continue
        if pushed is not None:
            edited = pushed.get(nf_path) != sha256_hex(remote)   # also: a file the last push did not write
        else:
            blob = commit_blob(m, rel, commit) if commit else None
            if blob is None:               # no usable commit: compare with this repo's copy
                out["baseline"] = "repo"
                edited = True
            else:
                seen = strip_stamps(remote) if rel.endswith(".html") else remote
                edited = lf_bytes(rel, seen) != blob
        if edited:
            out["drifted"].append(nf_path)
            out["remote"][nf_path] = remote
    return out


def baseline_text(drift: dict) -> str:
    return {"manifest": "what was last pushed", "commit": f"the copy in the installed commit {drift['commit'][:7]}",
            "repo": "this repo's copy"}.get(drift["baseline"], "the repo")


def save_remote_files(drift: dict, folder: Path) -> list[Path]:
    """Download (already read) hand-edited box files under `folder`, keeping their NF paths. Returns the files."""
    root = folder.expanduser().resolve()
    saved = []
    for nf_path, data in drift["remote"].items():
        target = (root / nf_path.lstrip("/")).resolve()
        if root not in target.parents:
            raise SystemExit(f"refusing to save {nf_path!r} outside {root}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        saved.append(target)
    return saved


def guard_pushed_files(c, m: dict, force: bool = False, save_remote: Path | None = None,
                       only: set[str] | None = None) -> int:
    """Run before a push writes anything. 0 = go ahead; EXIT_DRIFT = stop (nothing was written).
    `only` limits the check to those NF paths."""
    drift = find_drift(c, m, only)
    if drift["baseline"] == "none" or not drift["checked"]:
        return 0
    if drift["baseline"] != "manifest":
        print("push: WARNING: the box has no push manifest (it was installed by an older release), so a hand edit cannot "
              f"be told from an older version; comparing each file on the box with {baseline_text(drift)}")
    names = drift["drifted"]
    if not names:
        print(f"push: no hand-edited files on the box ({drift['checked']} files match {baseline_text(drift)})")
        return 0
    if save_remote:
        saved = save_remote_files(drift, save_remote)
        print(f"push: saved {len(saved)} box copies of the files below to {save_remote} (for review)")
    if force:
        print(f"push: --force: overwriting {len(names)} file(s) on the box that differ from {baseline_text(drift)}:")
        for n in names:
            print(f"  {n}")
        return 0
    print(f"push: STOPPED: {len(names)} file(s) on the box differ from {baseline_text(drift)} (hand-edited on the box):")
    for n in names:
        print(f"  {n}")
    print("Pushing would overwrite them; nothing was written. To keep their changes: re-run with --save-remote DIR "
          "(downloads the box copies to DIR for review), land the edits in the repo, then push. "
          "To overwrite them anyway: re-run with --force.")
    return EXIT_DRIFT


# ---------------------------------------------------------------- push

def cmd_push(c: Console, m: dict, skip_hooks: bool = False, only_hooks: list[str] | None = None,
             skip_deps: bool = False, clock=time.monotonic, sleep=time.sleep,
             force: bool = False, save_remote: Path | None = None, skip_auth: bool = False,
             on_mutation=None) -> int:
    spec = m["application"]
    app_id = spec["id"]
    if spec.get("name") and app_slug(spec["name"]) != app_id:
        raise SystemExit(f"manifest id {app_id!r} != NF's id for name {spec['name']!r} ({app_slug(spec['name'])!r}); "
                         "NF ignores the id on create, so make them match")
    rc = guard_pushed_files(c, m, force, save_remote)   # before anything is written
    if rc:
        return rc
    if not c.app(app_id):
        if on_mutation:
            on_mutation()
        print(f"creating app {app_id}")
        c.call("POST", "/api/v1/apps", spec)
        for _ in range(30):
            a = c.app(app_id)
            if a and a.get("status") == INSTALLED:
                break
            sleep(2)
    elif spec.get("auth") and not skip_auth:
        if on_mutation:
            on_mutation()
        c.call("PATCH", f"/api/v1/apps/{app_id}", {"id": app_id, "auth": spec["auth"], "updateMask": ["auth"]})
    elif on_mutation:
        on_mutation()
    pushed: dict[str, str] = {}      # sha256 of every file this push wrote: the baseline of the next push's guard
    for nf_path, rel in m["files"].items():
        data = deploy_bytes(m, rel)
        # WriteFile maps the HTTP body to the bytes field: send a JSON string of base64.
        c.call("POST", f"/api/v1/apps/{app_id}/files{nf_path}", base64.b64encode(data).decode())
        pushed[nf_path] = sha256_hex(data)
        print(f"wrote {nf_path} ({len(data)} bytes)")
    # Dependencies BEFORE the hooks are (re)started: a scheduled hook fires right after the restart, and one that
    # starts without its packages records a failed run.
    if not skip_deps:
        report_deps(install_deps(c, m, clock, sleep), app_id)
    # The version the UI shows (static/version.js): generated from the repo, never committed.
    info = version_info(m["_dir"])
    info[PUSH_MANIFEST_KEY] = pushed     # the push manifest: what a later push / doctor compares the box against
    c.call("POST", f"/api/v1/apps/{app_id}/files/static/version.json",
           base64.b64encode(json.dumps(info).encode()).decode())
    print(f"wrote /static/version.json (v{info['version']} {info['commit'][:7]}{'+dirty' if info['dirty'] else ''})")
    # NF's app record has no version field (and ignores description updates), so record the
    # installed revision as a read-only app setting "version" — shown in the NF console's app
    # settings and returned by GET /api/v1/apps. Other options the app has are kept.
    stamp = info["version"] + (f" ({info['commit'][:7]}{'+' if info['dirty'] else ''})" if info["commit"] else "")
    current = (c.app(app_id) or {}).get("options", [])
    opt = {"name": "version", "description": "Installed Open-FDD revision (set on deploy by nf_app_sync.py)",
           "optionType": "TYPE_STRING", "defaultValue": {"string": stamp}, "value": {"string": stamp}}
    try:
        # 1) define the option, 2) set its value (NF stores the two separately).
        c.call("PATCH", f"/api/v1/apps/{app_id}", {"id": app_id, "updateMask": ["options"],
               "options": [o for o in current if o.get("name") != "version"] + [opt]})
        c.call("PATCH", f"/api/v1/apps/{app_id}", {"id": app_id, "updateMask": ["configuration"],
               "configuration": {"version": {"string": stamp}}})
        print(f"app setting version = {stamp}")
    except SystemExit as e:  # older NF: version.json still carries the revision
        print(f"could not set the app's version option ({e}); version.json still shows the revision")
    for hook in [] if skip_hooks else [h for h in m["hooks"] if not only_hooks or h["id"] in only_hooks]:
        # UpdateHook maps the HTTP body to the hook message itself.
        c.call("POST", f"/api/v1/apps/{app_id}/hooks", hook)
        print(f"updated hook {hook['id']}")
    # The runtime caches the hook module (and the installed packages); restart so new code is loaded.
    c.call("PATCH", f"/api/v1/apps/{app_id}/restart", {})
    print("restarted app runtimes")
    return 0


# ---------------------------------------------------------------- run

ACTIVE_STATES = ("STATE_RUNNING", "STATE_ENQUEUED", "STATE_SCHEDULED")
EXIT_FAILED = 1
EXIT_STILL_RUNNING = 3  # the wait ran out; the run itself was NOT stopped or restarted
POLL_SECONDS = 2
WAIT_GRACE_SECONDS = 60  # added to the hook's invokeTimeout for the default wait
DEFAULT_INVOKE_TIMEOUT = 300.0  # when a hook definition has no invokeTimeout


def parse_duration(text, default: float = DEFAULT_INVOKE_TIMEOUT) -> float:
    """Seconds from an NF duration such as "300s", "90s", "5m", "1h" or "1.5s"; default if unparseable."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*", str(text or ""))
    if not m:
        return default
    return float(m.group(1)) * {"ms": 0.001, None: 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}[m.group(2)]


def default_wait(hook: dict) -> float:
    """How long `run` waits by default: the hook's invokeTimeout plus a minute, so a run NF itself
    would still let finish is not reported as lost."""
    return parse_duration(hook.get("invokeTimeout")) + WAIT_GRACE_SECONDS


def find_run(c, app_id: str, hook_id: str, pid):
    """The run with this pid (last 20 runs, with results and logs), or None. API errors raise SystemExit/OSError."""
    runs = c.call("GET", f"/api/v1/apps/{app_id}/hooks/{hook_id}/runs"
                         "?page_size=20&include_results=true&include_logs=true").get("runs", [])
    return next((x for x in runs if x.get("pid") == pid), None)


def wait_for_run(c, app_id: str, hook_id: str, pid, wait: float, clock=time.monotonic, sleep=time.sleep):
    """Poll until the run leaves the active states or `wait` seconds pass. Returns the finished run,
    or None on timeout. Never starts anything: a failed poll is retried, not answered with a re-run."""
    deadline = clock() + wait
    while clock() < deadline:
        sleep(min(POLL_SECONDS, max(0.0, deadline - clock())))
        try:
            run = find_run(c, app_id, hook_id, pid)
        except (SystemExit, OSError) as e:  # transient console/network error: keep waiting
            print(f"  (could not read the run state: {e}; still waiting)")
            continue
        if run and run.get("state") not in ACTIVE_STATES:
            return run
    return None


def result_failure(run: dict) -> str | None:
    """The error text when a finished run's hook RETURNED ok:false (NF still calls the run STATE_SUCCESS), else None.
    Looks at the result objects of the run and at JSON event lines (hooks also log their answer as one line)."""
    for g in (run.get("results") or {}).values():
        for key in ("result", "value", "output", "returnValue"):
            v = g.get(key)
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    v = None
            if isinstance(v, dict) and v.get("ok") is False:
                return str(v.get("error") or v.get("reason") or "ok: false")
        for e in g.get("events", []):
            try:
                v = json.loads(e.get("message") or "")
            except ValueError:
                continue
            if isinstance(v, dict) and v.get("ok") is False:
                return str(v.get("error") or v.get("reason") or "ok: false")
    return None


def run_error_text(run: dict) -> str:
    """All error/event text of a run, for matching known failures (missing packages)."""
    parts = []
    for g in (run.get("results") or {}).values():
        if g.get("error"):
            parts.append(str(g["error"].get("message")))
        parts.extend(str(e.get("message")) for e in g.get("events", []))
    return "\n".join(parts)


def fdd_unit_skip_text(run: dict) -> str | None:
    """Read the latest FDD run's unit skips, including consoles that return only event text."""
    for group in (run.get("results") or {}).values():
        for key in ("result", "value", "output", "returnValue"):
            result = group.get(key)
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    continue
            counts = result.get("roles_skipped_by_unit") if isinstance(result, dict) else None
            if isinstance(counts, dict):
                skips = {r: n for r, n in counts.items()
                         if isinstance(r, str) and re.fullmatch(r"[a-z][a-z0-9_]*", r) and type(n) is int and n > 0}
                if skips:
                    roles = ", ".join(f"{r} {n}" for r, n in sorted(skips.items()))
                    return f"roles skipped by unit: {sum(skips.values())} ({roles})"
    match = re.search(r"\broles skipped by unit: [1-9][0-9]*(?: \([a-z0-9_, ]+\))?", run_error_text(run))
    return match.group(0) if match else None


def _safe_print(text: str) -> None:
    """Print without crashing on Windows cp1252 consoles when hook events contain Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(getattr(sys, "stdout", None), "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def report_run(run: dict) -> int:
    _safe_print(f"  {run['state']} start={run.get('startTime')}")
    for g in (run.get("results") or {}).values():
        if g.get("error"):
            _safe_print(f"  error: {g['error'].get('message')}")
        for e in g.get("events", []):
            _safe_print(f"  event {e.get('ts')}: {e.get('message')}")
    bad = result_failure(run)
    if bad:
        _safe_print(f"  hook returned ok:false: {bad}")
        return EXIT_FAILED
    return 0 if run["state"] == "STATE_SUCCESS" else EXIT_FAILED


def select_runnable(hooks: list[dict], only_hooks: list[str] | None, args: dict | None):
    """(to_run, skipped): with no --hook, scheduled hooks run and on-request hooks only when args were given
    (the rest are skipped: they would only answer "args required"). --hook IDs always run, args or not."""
    if only_hooks:
        return [h for h in hooks if h["id"] in only_hooks], []
    run, skipped = [], []
    for h in hooks:
        (skipped if h.get("mode") == ON_REQUEST and not args else run).append(h)
    return run, skipped


def cmd_run(c, m: dict, only_hooks: list[str] | None = None, wait: float | None = None,
            resume: int | None = None, clock=time.monotonic, sleep=time.sleep,
            args: dict | None = None) -> int:
    """Start each selected hook once and wait for it. Exit 0 = all succeeded, 1 = a run failed (or a hook returned
    ok:false), 3 = a wait ran out with the run still going (check it, or `--resume PID`); 1 wins over 3.
    --resume PID waits on an existing run of the single selected hook and starts nothing.
    Without --hook only scheduled hooks run, plus on-request hooks given --arg values; the others are
    reported as skipped (needs args), which is not a failure."""
    app_id = m["application"]["id"]
    hooks, skipped = select_runnable(m["hooks"], only_hooks, args)
    if resume is not None and len(hooks) != 1:
        raise SystemExit("--resume needs exactly one hook: pass --hook ID")
    for h in skipped:
        print(f"skipped (needs args): {h['id']} (on-request; pass --arg KEY=VALUE or --hook {h['id']} to run it)")
    rc = 0
    for hook in hooks:
        limit = wait if wait is not None else default_wait(hook)
        if resume is not None:
            pid = resume
            print(f"waiting for {hook['id']} pid={pid} (up to {limit:.0f} s)")
        else:
            body = dict(args or {}) if hook.get("mode") == ON_REQUEST else {}
            pid = c.call("POST", f"/api/v1/apps/{app_id}/hooks/{hook['id']}", body).get("pid")
            print(f"started {hook['id']} pid={pid} (waiting up to {limit:.0f} s)")
        run = wait_for_run(c, app_id, hook["id"], pid, limit, clock, sleep)
        if run is None:
            print(f"  still running after {limit:.0f} s: {hook['id']} pid={pid}. NOT restarted. "
                  f"Wait again with: run <manifest> --hook {hook['id']} --resume {pid}")
            rc = rc or EXIT_STILL_RUNNING
        elif report_run(run):
            print(f"FAILED: hook {hook['id']}")
            rc = EXIT_FAILED
    return rc


# ---------------------------------------------------------------- pull / diff

def cmd_pull(c: Console, m: dict, write: bool) -> int:
    app_id = m["application"]["id"]
    changed = 0
    for nf_path, rel in m["files"].items():
        remote = c.read_file(app_id, nf_path)
        local_path = m["_dir"] / rel
        local = deploy_bytes(m, rel) if local_path.exists() else b""
        if remote is None:
            print(f"{nf_path}: missing on NF")
            changed += 1
            continue
        if remote == local:
            print(f"{nf_path}: in sync")
            continue
        changed += 1
        if write:
            local_path.write_bytes(strip_stamps(remote) if rel.endswith(".html") else remote)
            print(f"{nf_path}: pulled into {local_path}")
        else:
            sys.stdout.writelines(difflib.unified_diff(
                local.decode(errors="replace").splitlines(True), remote.decode(errors="replace").splitlines(True),
                f"repo/{rel}", f"nf{nf_path}"))
    return 1 if (changed and not write) else 0


# ---------------------------------------------------------------- install / remove-old / uninstall

def replaced_ids(m: dict) -> list[str]:
    """Predecessor app ids from the manifest's optional top-level `replaces` (never the app's own id)."""
    own = m["application"]["id"]
    return [i for i in dict.fromkeys(m.get("replaces") or []) if i != own]


def preflight(c, m: dict) -> dict:
    """Check auth (raises the clear 401 message), then report this app and its predecessors on the box."""
    apps = {a["id"]: a for a in c.apps()}   # a 401 here carries the which-layer explanation
    app_id = m["application"]["id"]
    print("preflight: console login accepted")
    cur = apps.get(app_id)
    if cur:
        print(f"preflight: {app_id} already installed, version {option_value(cur, 'version') or 'unknown'} "
              f"(status {cur.get('status')})")
    else:
        print(f"preflight: {app_id} not installed yet")
    for old in replaced_ids(m):
        if old in apps:
            print(f"preflight: predecessor {old} is installed (version {option_value(apps[old], 'version') or 'unknown'})")
    return apps


def query_pages(c, body: dict) -> list[dict]:
    """POST /api/v1/point/query, every page (read-only). NF pages by pageOffset + totalCount, not only by a
    next-page token (#1550): the shared pager (scripts/nf/nf_paging.py) follows either and never returns a truncated
    list: a cap, a paging loop or a short read stops with a PagingError message."""
    return page_all(lambda p: c.call("POST", "/api/v1/point/query", {**body, **p}) or {}, "points", what="point/query")


def automation_points(c) -> list[dict]:
    return query_pages(c, {"layer": "automation"})


def orphan_points(points: list[dict], installed: set[str], removing: set[str]) -> list[dict]:
    """Automation-layer points whose attrs.application_id names an app that is gone or about to be. Points of any
    app that stays installed, and points with no application_id (not hook-created), are never listed."""
    live = installed - removing
    return [p for p in points
            if (p.get("attrs") or {}).get("application_id") and p["attrs"]["application_id"] not in live]


def list_orphans(c, installed: set[str], removing: set[str]) -> list[dict]:
    try:
        orphans = orphan_points(automation_points(c), installed, removing)
    except SystemExit as e:
        print(f"could not list automation-layer points ({e})")
        return []
    if not orphans:
        print("orphan points: none")
        return orphans
    print(f"orphan automation-layer points (application_id is a removed/absent app): {len(orphans)}")
    for p in orphans:
        print(f"  {p.get('uuid')}  {p.get('name')}  application_id={p['attrs']['application_id']}")
    return orphans


ORPHAN_HOWTO = ("orphan points are never deleted by this tool. Delete them with the NF MCP delete_points tool "
                "(dry run first), checking attrs.application_id of each uuid. Never delete points of other apps or "
                "BACnet/field layers")


def remove_apps(c, ids: list[str], yes: bool, installed: dict[str, dict]) -> int:
    """Dry run unless `yes`: list (or DELETE /api/v1/apps/<id>) each installed app in `ids`, then list orphan points."""
    present = [i for i in ids if i in installed]
    if not present:
        print("no predecessor/target apps installed: nothing to remove")
    for i in present:
        v = option_value(installed[i], "version") or "unknown"
        if yes:
            c.call("DELETE", f"/api/v1/apps/{i}")
            print(f"removed app {i} (version {v})")
        else:
            print(f"would remove app {i} (version {v})")
    ids_now = set(installed) - (set(present) if yes else set())
    orphans = list_orphans(c, ids_now, set(present) if not yes else set())
    if orphans:
        print(ORPHAN_HOWTO)
    if not yes and (present or orphans):
        print("dry run: nothing was changed; add --yes to act")
    return 0


def cmd_remove_old(c, m: dict, yes: bool) -> int:
    apps = {a["id"]: a for a in c.apps()}
    return remove_apps(c, replaced_ids(m), yes, apps)


def cmd_uninstall(c, m: dict, yes: bool) -> int:
    apps = {a["id"]: a for a in c.apps()}
    app_id = m["application"]["id"]
    if app_id not in apps:
        print(f"app {app_id}: not installed")
    return remove_apps(c, [app_id], yes, apps)


def verify_install(c, m: dict, skip_run: bool = False, wait: float | None = None,
                   clock=time.monotonic, sleep=time.sleep) -> int:
    """Version matches the repo; every scheduled hook run once AFTER the dependencies are in. 0 = good."""
    app_id = m["application"]["id"]
    rc = 0
    want = version_info(m["_dir"])["version"]
    a = c.app(app_id)
    raw = c.read_file(app_id, "/static/version.json")
    try:
        got = json.loads(raw.decode()).get("version") if raw else None
    except ValueError:
        got = None
    opt = option_value(a, "version")
    if got == want:
        print(f"verify: version.json = {got} (matches the repo)")
    else:
        print(f"verify: FAILED version.json = {got!r}, repo = {want!r}")
        rc = EXIT_FAILED
    if opt is not None:
        print(f"verify: app setting version = {opt}")
    if rc:
        # A broken version is a terminal verification failure; do not launch hooks from the bad release.
        return rc
    scheduled = [h["id"] for h in m["hooks"] if h.get("mode") != ON_REQUEST]
    if skip_run or not scheduled:
        return rc
    print(f"verify: first run of the scheduled hooks ({', '.join(scheduled)}), after the dependencies:")
    r = cmd_run(c, m, scheduled, wait, None, clock, sleep)
    if r:
        print("verify: FAILED: a scheduled hook did not succeed (output above)")
        rc = r
    return rc


def cmd_install(c, m: dict, a, clock=time.monotonic, sleep=time.sleep) -> int:
    apps = preflight(c, m)
    app_id = m["application"]["id"]
    prior = (c.app(app_id) if apps.get(app_id) else None) or apps.get(app_id)
    dry_run = getattr(a, "dry_run", False)
    # Schema preflight precedes even the remote-file snapshot reads, then all reads precede mutation. When the installed
    # app has no (or an older) NF-side schema probe, the gate bootstraps just the probe first (#1593).
    lvl, message, bootstrapped = install_schema_gate(c, m, a, prior, app_id, getattr(a, "_environ", os.environ),
                                                     clock, sleep, dry_run)
    if lvl == "DRIFT":
        print(f"install: STOPPED (exit {EXIT_DRIFT}): hand-edited files on the box (see above); the box was not changed")
        return EXIT_DRIFT
    if lvl == "FAIL":
        print(f"install: STOPPED: Timescale schema preflight failed: {message}")
        return EXIT_FAILED
    if lvl == "DRYRUN":
        print(f"install: dry run: {message}")
    elif lvl == "PASS" and message:
        print(f"install: Timescale schema preflight: {message}")
    if bootstrapped:
        prior = c.app(app_id) or prior     # the snapshot below must include the bootstrapped probe
    rc = guard_pushed_files(c, m, getattr(a, "force", False), getattr(a, "save_remote", None))
    if rc == EXIT_DRIFT:
        print(f"install: STOPPED (exit {rc}): hand-edited files on the box (see above); the box was not changed")
        return rc
    if dry_run:
        print("install: dry run: nothing was changed; re-run without --dry-run to install")
        return 0
    if prior:
        # NF 3.10's DELETE file/hook routes are documented. Snapshot existing targets; track new ones
        # separately so a failed verification can remove them without touching older app content.
        listed_files = prior.get("files")
        listed_hooks = prior.get("hooks")
        if not isinstance(listed_files, list) or not isinstance(listed_hooks, list):
            print("install: STOPPED: NF did not provide a complete files/hooks listing; cannot snapshot a rollback image")
            return EXIT_FAILED
        known = {x.get("path") for x in listed_files if isinstance(x, dict) and x.get("path")}
        paths = set(m["files"]) | {"/static/version.json"}
        new_paths = paths - known
        old_paths = paths & known
        old_files = {}
        try:
            for path in old_paths:
                data = c.read_file(app_id, path, known_paths=known)
                if data is None:
                    raise SystemExit(f"{path} is missing")
                old_files[path] = data
        except SystemExit as e:
            print(f"install: STOPPED: could not snapshot rollback image ({e}); nothing was written")
            return EXIT_FAILED
        old_hooks = {h.get("id"): h for h in prior.get("hooks", []) if h.get("id")}
        intended_hooks = {h["id"] for h in m["hooks"] if not a.hooks or h["id"] in a.hooks} if not a.skip_hooks else set()
        new_hooks = intended_hooks - set(old_hooks)
        old_options = prior.get("options", [])
        old_configuration = prior.get("configuration", {})
    else:
        old_files = old_hooks = old_options = old_configuration = None
        new_paths = new_hooks = set()
        intended_hooks = set()

    def rollback() -> bool:
        if not prior or old_files is None:
            return False
        print("install: restoring the previous app snapshot")
        cleanup_failures = []
        if new_paths or new_hooks:
            current = None
            try:
                current = c.app(app_id) or {}
                if not isinstance(current.get("files"), list) or not isinstance(current.get("hooks"), list):
                    current = None
                    cleanup_failures.append("NF app listing omitted files/hooks; cannot identify new assets")
            except SystemExit:
                cleanup_failures.append("NF app listing unavailable; cannot identify new assets")
            if current is not None:
                present_hooks = {h.get("id") for h in current["hooks"] if h.get("id")}
                present_paths = {x.get("path") for x in current["files"] if isinstance(x, dict) and x.get("path")}
                for hook_id in new_hooks & present_hooks:
                    # Normal Framework DeleteHook removes its definition/runtime and leaves hook source files.
                    try:
                        c.call("DELETE", f"/api/v1/apps/{app_id}/hooks/{urllib.parse.quote(hook_id, safe='')}")
                    except SystemExit:
                        cleanup_failures.append(f"new hook {hook_id} could not be deleted")
                for path in new_paths & present_paths:
                    try:
                        c.call("DELETE", f"/api/v1/apps/{app_id}/files{path}")
                    except SystemExit:
                        cleanup_failures.append(f"new file {path} could not be deleted")
                try:
                    after = c.app(app_id) or {}
                    if not isinstance(after.get("files"), list) or not isinstance(after.get("hooks"), list):
                        cleanup_failures.append("NF app listing omitted files/hooks after cleanup")
                    else:
                        remaining_hooks = {h.get("id") for h in after["hooks"] if h.get("id")}
                        remaining_paths = {x.get("path") for x in after["files"] if isinstance(x, dict) and x.get("path")}
                        cleanup_failures.extend(f"new hook {h} remains" for h in new_hooks & remaining_hooks)
                        cleanup_failures.extend(f"new file {p} remains" for p in new_paths & remaining_paths)
                except SystemExit:
                    cleanup_failures.append("NF app listing unavailable after cleanup")
        try:
            for path, data in old_files.items():
                c.call("POST", f"/api/v1/apps/{app_id}/files{path}", base64.b64encode(data).decode())
            c.call("PATCH", f"/api/v1/apps/{app_id}", {"id": app_id, "updateMask": ["options"], "options": old_options})
            c.call("PATCH", f"/api/v1/apps/{app_id}", {"id": app_id, "updateMask": ["configuration"],
                                                           "configuration": old_configuration})
            if not a.skip_hooks:
                for hook_id in intended_hooks & set(old_hooks):
                    c.call("POST", f"/api/v1/apps/{app_id}/hooks", old_hooks[hook_id])
            c.call("PATCH", f"/api/v1/apps/{app_id}/restart", {})
            if cleanup_failures:
                print("install: ROLLBACK INCOMPLETE: " + ", ".join(cleanup_failures) + " remain after cleanup")
                return False
            if new_paths or new_hooks:
                print("install: removed newly added files and hooks; previous files, settings and hooks restored")
            else:
                print("install: previous files, settings and hooks restored")
            return True
        except SystemExit as e:
            print(f"install: ROLLBACK INCOMPLETE: {e}")
            return False

    mutation_started = False
    def mark_mutation():
        nonlocal mutation_started
        mutation_started = True
    try:
        rc = cmd_push(c, m, a.skip_hooks, a.hooks, a.skip_deps, clock, sleep,
                      getattr(a, "force", False), getattr(a, "save_remote", None), skip_auth=True,
                      on_mutation=mark_mutation)
    except SystemExit as e:
        print(f"install: push failed ({e})")
        if mutation_started:
            rollback()
        return EXIT_FAILED
    if rc == EXIT_DRIFT:      # hand-edited files on the box: nothing was written, nothing to verify
        print(f"install: STOPPED (exit {rc}): hand-edited files on the box (see above); the box was not changed")
        return rc
    try:
        rc = verify_install(c, m, a.skip_verify_run, a.wait, clock, sleep) or rc
    except SystemExit as e:
        print(f"install: verification could not complete: {e}")
        rc = EXIT_FAILED
    if rc and prior and old_files is not None:
        if rc == EXIT_STILL_RUNNING:
            print("install: verification is still running; no rollback or predecessor removal was attempted. Resume the reported pid after it finishes")
            return rc
        print("install: verification failed")
        rollback()
        return rc
    if a.remove_old:
        if rc:
            print("not removing the predecessor apps: the install did not verify")
            ids = replaced_ids(m)
            remove_apps(c, ids, False, apps)   # list only
        else:
            apps = {x["id"]: x for x in c.apps()}
            rc = remove_apps(c, replaced_ids(m), a.yes, apps)
    elif replaced_ids(m) and any(i in apps for i in replaced_ids(m)):
        print("predecessor apps are still installed; re-run with --remove-old (add --yes to delete them)")
    print("install: " + ("OK" if rc == 0 else f"finished with problems (exit {rc})"))
    return rc


# ---------------------------------------------------------------- doctor

def coords_ok(rec_attrs: dict) -> bool:
    try:
        la, lo = float(rec_attrs.get("latitude")), float(rec_attrs.get("longitude"))
        return not (la == 0 and lo == 0)
    except (TypeError, ValueError):
        return bool(re.search(r"C\(\s*-?\d", str(rec_attrs.get("geoCoord") or "")))


def option_scalar(app: dict | None, name: str):
    """The value of an app option as a Python scalar (string / number / bool), or None when the option is not defined
    or its value is empty. NF shows a value as {"string": ..} / {"double": ..} / {"signed": ..} / {"boolean": ..}."""
    for o in (app or {}).get("options", []):
        if o.get("name") != name:
            continue
        for v in ((o.get("value") or {}).values()):
            if v is not None and str(v).strip() != "":
                return v
    return None


def option_defined(app: dict | None, name: str) -> bool:
    return any(o.get("name") == name for o in (app or {}).get("options", []))


def option_coords(app: dict | None) -> tuple[float, float] | None:
    """(latitude, longitude) from the app options the weather hook reads first; None when unset (both 0 = unset)."""
    try:
        la, lo = float(option_scalar(app, "latitude")), float(option_scalar(app, "longitude"))
    except (TypeError, ValueError):
        return None
    return None if (la == 0 and lo == 0) or abs(la) > 90 or abs(lo) > 180 else (la, lo)


def weather_coords_source(c, app: dict | None = None) -> tuple[str, str]:
    """('pass'|'fail', text): where the weather hook would get its coordinates, in the hook's own order:
    the app options latitude + longitude, NF Sites, then the modeled Haystack site."""
    if option_coords(app):
        return "pass", "app options latitude/longitude are set (the weather hook reads them first)"
    try:
        def _sites_page(p):
            q = [f"pageSize={p['pageSize']}"]
            if p.get("pageOffset"):
                q.append(f"pageOffset={p['pageOffset']}")
            if p.get("pageToken"):
                from urllib.parse import quote
                q.append(f"pageToken={quote(str(p['pageToken']), safe='')}")
            return c.call("GET", "/api/v1/sites?" + "&".join(q)) or {}
        sites = page_all(_sites_page, "sites", what="sites")
    except SystemExit as e:
        sites = []
        note = f" (sites API: {e})"
    else:
        note = ""
    if any(coords_ok(s) for s in sites):
        return "pass", "NF Sites API has coordinates"
    for layer in ("model", "site"):
        try:
            pts = query_pages(c, {"layer": layer})
        except SystemExit as e:
            if isinstance(e, PagingError):    # a truncated model must not read as "no coordinates"
                return "fail", f"could not read the {layer} layer completely: {e}"
            continue
        for p in pts:
            if (layer == "site" or p.get("pointType") == "SITE") and coords_ok(p.get("attrs") or {}):
                return "pass", f"modeled Haystack site on the {layer} layer has coordinates (NF Sites has none)"
    return "fail", ("no coordinates in the app options, NF Sites or on the modeled SITE; the weather hook will fail. "
                    'Set the app options "latitude" and "longitude" (NF console > app settings), or latitude/longitude '
                    "on the NF site or the modeled site" + note)


IANA_SHAPE = re.compile(r"^(UTC|GMT|[A-Za-z]+(/[A-Za-z0-9_+\-]+)+)$")


def timezone_source(c, app: dict | None = None) -> tuple[str, str]:
    """('pass'|'warn', text): where the UI gets the site timezone, in the UI's own order (#1584): the modeled site's
    tz/timezone, the app option "timezone", then the NF Sites API timezone. None of them = the charts fall back to
    the browser zone or UTC and label it "(fallback)". Read-only."""
    opt = option_scalar(app, "timezone")
    opt_ok = isinstance(opt, str) and bool(IANA_SHAPE.match(opt.strip()))
    sites_missing, n_sites = 0, 0
    for layer in ("model",):
        try:
            recs = query_pages(c, {"layer": layer})
        except SystemExit as e:
            if isinstance(e, PagingError):
                return "warn", f"could not read the {layer} layer completely: {e}"
            recs = []
        for p in recs:
            if p.get("pointType") == "SITE":
                n_sites += 1
                a = p.get("attrs") or {}
                if not (a.get("tz") or a.get("timezone")):
                    sites_missing += 1
    if n_sites and not sites_missing:
        return "pass", "every modeled site has a tz (the UI uses it first)"
    if opt_ok:
        return "pass", f'app option "timezone" is set ({opt.strip()}); modeled sites without tz use it'
    bad = f' (the app option "timezone" is set but {opt!r} is not an IANA zone name such as America/Chicago)' if opt not in (None, "") else ""
    try:
        def _page(p):
            q = [f"pageSize={p['pageSize']}"]
            if p.get("pageOffset"):
                q.append(f"pageOffset={p['pageOffset']}")
            return c.call("GET", "/api/v1/sites?" + "&".join(q)) or {}
        api_sites = page_all(_page, "sites", what="sites")
    except SystemExit:
        api_sites = []
    if any(s.get("timezone") for s in api_sites):
        return "pass", "NF Sites API has a timezone (used when the model site has no tz and no app option is set)"
    return "warn", ("UTC fallback (no site tz on the modeled site, no app option, no NF Sites timezone): range pickers and "
                    "hour labels show UTC" + bad + '. Set the app option "timezone" to an IANA zone such as America/Chicago '
                    "(NF console > app settings); no points need retagging")


RRULE_SECONDS = {"SECONDLY": 1, "MINUTELY": 60, "HOURLY": 3600, "DAILY": 86400, "WEEKLY": 604800}
DEFAULT_FDD_INTERVAL = 3600


def rrule_interval_seconds(rrule: str | None) -> int | None:
    """Seconds between runs for a simple FREQ/INTERVAL rule (the app's own schedules), else None."""
    freq = re.search(r"FREQ=([A-Z]+)", rrule or "")
    if not freq or freq.group(1) not in RRULE_SECONDS:
        return None
    n = re.search(r"INTERVAL=(\d+)", rrule or "")
    return RRULE_SECONDS[freq.group(1)] * max(1, int(n.group(1)) if n else 1)


def parse_ts(value) -> datetime.datetime | None:
    """ISO 8601 (Z or offset, any fractional digits) -> aware UTC datetime; None when it is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        t = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def human_age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def fdd_freshness(c, interval: int, now: datetime.datetime) -> tuple[str, str]:
    """('pass'|'warn'|'fail', text): how old the computed FDD points are against the newest raw history sample.

    Computed = the newest of: a result point's latest value, fddLastRun of a result that is not flagged stale, and a
    fault timeline's fddTimelineThrough (fddLastRun alone is rewritten when a result is only flagged stale, so it
    would hide a frozen point). Raw = newest latest value of any trended point that is not an FDD result. Read-only."""
    pts = query_pages(c, {"layer": "default", "structuredQuery": {"field": {"property": "markers", "text": "his"}}})
    computed: list[datetime.datetime] = []
    raw: list[datetime.datetime] = []
    stale_reasons: dict[str, int] = {}
    stale_timelines = 0
    results = 0
    for p in pts:
        a = p.get("attrs") or {}
        latest = parse_ts((p.get("latestValue") or {}).get("ts"))
        if a.get("ruleRef") and (a.get("fddStatus") or a.get("fddKind") or a.get("fddLastRun")):
            results += 1
            if latest:
                computed.append(latest)
            if a.get("fddStatus") == "stale":
                if a.get("fddKind") == "fault-timeline":     # a companion of a result: counted apart (#1586)
                    stale_timelines += 1
                else:
                    why = re.sub(r"\s*\(.*$", "", str(a.get("fddReason") or "no reason recorded"))[:60]
                    stale_reasons[why] = stale_reasons.get(why, 0) + 1
            elif parse_ts(a.get("fddLastRun")):
                computed.append(parse_ts(a.get("fddLastRun")))
            if parse_ts(a.get("fddTimelineThrough")):
                computed.append(parse_ts(a.get("fddTimelineThrough")))
        elif latest:
            raw.append(latest)
    limit = 2 * interval
    if not results:
        return "warn", "no FDD result points yet (the fdd hook has not published; run it once)"
    if not raw:
        return "warn", f"{results} FDD result points, but no raw history sample was found to compare with"
    c_new, r_new = (max(computed) if computed else None), max(raw)
    r_age = (now - r_new).total_seconds()
    c_age = (now - c_new).total_seconds() if c_new else None
    sched = f"fdd runs every {human_age(interval)}"
    why = "; ".join(f"{k} x{n}" for k, n in sorted(stale_reasons.items(), key=lambda kv: -kv[1]))
    stale_note = f"; {sum(stale_reasons.values())} results flagged stale ({why})" if stale_reasons else ""
    if stale_timelines:
        stale_note += f"; {stale_timelines} fault timelines flagged stale"
    if c_age is not None and c_age <= limit:
        return "pass", (f"computed results {human_age(max(c_age, 0))} old (newest {c_new:%Y-%m-%dT%H:%M:%SZ}), raw history "
                        f"{human_age(max(r_age, 0))} old; {sched}{stale_note}")
    if r_age > limit:
        return "warn", (f"raw history is also stale (newest sample {human_age(r_age)} ago, {r_new:%Y-%m-%dT%H:%M:%SZ}): "
                        f"the data source is not delivering, not the fdd hook alone; {sched}")
    got = f"{human_age(c_age)} old (newest {c_new:%Y-%m-%dT%H:%M:%SZ})" if c_new else "never written a value"
    return "fail", (f"computed results {got}, more than 2x the schedule ({sched}) while raw history is fresh "
                    f"(newest sample {human_age(max(r_age, 0))} ago){stale_note}. The fdd hook is not producing output: "
                    "read its last run (include_results=true) for the per-equip skip reasons")


def timescale_check(app: dict) -> tuple[str, str]:
    """('PASS'|'WARN'|'FAIL', text): can the hooks read a Timescale connection? Judged the way the hooks read it
    (hooks/lib/settings.js): the app option "timescale" is a JSON string with host / connectionString (or a postgres://
    URL); NF stores no hook-definition config. The value is never printed."""
    engine = str(option_scalar(app, "engine") or "").lower()
    raw = option_scalar(app, "timescale")
    if raw is None:
        if option_defined(app, "timescale"):
            return "WARN", ('app option "timescale" is defined but has no value (or NF does not show it here); the hooks '
                            "read it as ctx.config: run the history hook once to confirm")
        if any((h.get("config") or {}).get("timescale") for h in app.get("hooks", [])):
            return "WARN", ("a hook-definition config \"timescale\" is set, but NF 3.10.x does not store hook config "
                            'for hooks to read: set the app option "timescale" instead (docs/install.md)')
        if engine == "timescale":
            return "FAIL", ('engine option is "timescale" but no Timescale connection setting was found: set the app '
                            'option "timescale" (JSON string {"host","port","database","user","password"} or a postgres:// URL)')
        return "PASS", "not configured (history hook skips with a notice; fdd uses sqlite/pglite)"
    text = str(raw).strip()
    if re.match(r"postgres(ql)?://", text, re.I):
        return "PASS", 'app option "timescale" is a postgres:// URL (value not shown)'
    try:
        obj = json.loads(text) if text.startswith("{") else None
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        return "FAIL", ('app option "timescale" is set but is not valid JSON (an object with host) or a postgres:// URL, '
                        "so the hooks cannot read it (value not shown)")
    if not (obj.get("host") or obj.get("connectionString")):
        return "FAIL", 'app option "timescale" parses but has no "host" or "connectionString" (value not shown)'
    return "PASS", 'app option "timescale" parses and names a host (value not shown)'


def timescale_connection_host(value) -> str | None:
    """Extract the configured PostgreSQL host without exposing the connection value."""
    if isinstance(value, dict):
        value = value.get("connectionString") or value.get("host")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("{"):
        try:
            config = json.loads(text)
        except ValueError:
            return None
        return timescale_connection_host(config) if isinstance(config, dict) else None
    try:
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme.lower() in ("postgres", "postgresql"):
            return parsed.hostname
        if not parsed.scheme and "=" not in text:
            return text
    except ValueError:
        return None
    if "=" in text:
        import shlex
        found = None
        try:
            for part in shlex.split(text):
                key, sep, host = part.partition("=")
                if sep and key == "host":
                    found = host
        except ValueError:
            return None
        return found
    return None


def is_loopback_host(host: str | None) -> bool:
    """Recognize localhost and every IPv4/IPv6 loopback address, including mapped IPv4."""
    if not host:
        return False
    name = host.strip().strip("[]").rstrip(".").lower()
    if name == "localhost":
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return address.is_loopback or bool(mapped and mapped.is_loopback)


PROBE_HOOK_ID = "schema"
PROBE_WAIT_SECONDS = 45
SCHEMA_REMEDY = ("install a PostgreSQL client (psql) and set NF_TIMESCALE_PREFLIGHT_DSN to a reachable DB endpoint, "
                 "or install a release that ships the NF-side schema probe (the `schema` hook), which needs neither")


def timescale_selected(app: dict) -> bool:
    """True when the app's options select Timescale (engine "timescale", or a connection set and the engine not forced off)."""
    engine = str(option_scalar(app, "engine") or "auto").strip().lower()
    raw = option_scalar(app, "timescale")
    if engine in {"sqlite", "pglite"}:
        return False
    return engine == "timescale" or (raw is not None and str(raw).strip() != "")


def probe_result(run: dict) -> dict | None:
    """The {installed, required, ok} object a finished schema-probe run returned (result or JSON event line), else None."""
    def pick(v):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return None
        return v if isinstance(v, dict) and "required" in v else None
    for g in (run.get("results") or {}).values():
        for key in ("result", "value", "output", "returnValue"):
            if (found := pick(g.get(key))) is not None:
                return found
        for e in g.get("events", []):
            if (found := pick(e.get("message"))) is not None:
                return found
    return None


def has_probe_hook(app: dict) -> bool:
    return any(isinstance(h, dict) and h.get("id") == PROBE_HOOK_ID for h in app.get("hooks") or [])


def probe_run(c, app_id: str, clock=time.monotonic, sleep=time.sleep) -> dict | None:
    """Start the NF-side `schema` hook once and return its {installed, required, ok} answer, or None when the hook
    could not be started or the run gave no usable answer. Never raises."""
    try:
        pid = c.call("POST", f"/api/v1/apps/{app_id}/hooks/{PROBE_HOOK_ID}", {}).get("pid")
        run = wait_for_run(c, app_id, PROBE_HOOK_ID, pid, PROBE_WAIT_SECONDS, clock, sleep)
    except (SystemExit, OSError):
        return None
    return probe_result(run) if run else None


def schema_probe(c, app: dict, app_id: str, clock=time.monotonic, sleep=time.sleep) -> tuple[str, str] | None:
    """('PASS'|'FAIL'|'SKIP', text) from the NF-side read-only probe hook, or None when the installed app has no such
    hook or the run gave no usable answer (the caller then falls back to the DSN path). Only {installed, required, ok}
    comes back from NF; connection details never leave the hook."""
    if not has_probe_hook(app):
        return None
    got = probe_run(c, app_id, clock, sleep)
    return None if got is None else probe_verdict(got)


def probe_verdict(got: dict) -> tuple[str, str]:
    """('PASS'|'FAIL'|'SKIP', text) for a probe answer."""
    if got.get("skipped"):
        return "SKIP", ""
    required = got.get("required")
    if "installed" not in got:
        # the hook could not read the schema (error text is already redacted inside NF)
        return "FAIL", f"the NF-side schema probe could not read the Timescale schema: {str(got.get('error') or 'unknown error')[:200]}"
    installed = got.get("installed")
    if got.get("ok") is True:
        return "PASS", f"Timescale schema version {installed} (read by the NF-side probe)"
    return "FAIL", (f"Timescale schema version {installed}; this release requires {required}. "
                    "Run nf-app/timescale/install.sql as installer/owner")


# ---- bootstrapping the probe on an app that predates it (#1593)

# What hooks/schema.js needs at run time: itself, the two libs it requires, and static/units.js (required by
# lib/timescale.js). tests/test_nf_app_install.py checks this list against the real require() graph. The only npm
# package involved is pg (loaded lazily by lib/timescale.js), which every Timescale install already has.
PROBE_FILES = ("/hooks/schema.js", "/hooks/lib/settings.js", "/hooks/lib/timescale.js", "/static/units.js")
PROBE_DEP = "pg"
PROBE_LEFTOVER = ("The probe files and the `schema` hook were put on the box ahead of the install; nothing else was "
                  "changed (the app keeps its current version, hooks and settings).")


def manifest_ships_probe(m: dict) -> bool:
    """True when the manifest has the `schema` hook definition and every file the probe needs."""
    return (any(h.get("id") == PROBE_HOOK_ID for h in m.get("hooks") or [])
            and all(p in m["files"] and (m["_dir"] / m["files"][p]).is_file() for p in PROBE_FILES))


def local_required_schema(m: dict) -> int | None:
    """The schema version this release's hooks/lib/timescale.js requires (SCHEMA_VERSION), None if not readable."""
    rel = m["files"].get("/hooks/lib/timescale.js")
    try:
        found = re.search(r"^const SCHEMA_VERSION = (\d+);", (m["_dir"] / rel).read_text(encoding="utf-8"), re.M)
    except (OSError, TypeError):
        return None
    return int(found.group(1)) if found else None


def probe_cannot_run(why: str) -> str:
    return (f"the NF-side schema probe could not run ({why}), so the Timescale schema version was not checked. Either "
            "(a) forward the database to this machine, install a PostgreSQL client (psql) and set "
            "NF_TIMESCALE_PREFLIGHT_DSN to the forwarded endpoint, then re-run; or (b) fix the probe: make sure the app "
            f"dependencies ({PROBE_DEP}) are installed (PATCH /api/v1/apps/<app-id>/dependencies, then "
            "PATCH /api/v1/apps/<app-id>/restart), then re-run. " + PROBE_LEFTOVER)


def record_in_push_manifest(c, app_id: str, hashes: dict[str, str]) -> bool:
    """Add `hashes` ({nf_path: sha256}) to the box's push manifest (static/version.json "files") so a later push does
    not take those files for hand edits. A box with no push manifest is left alone (creating one would make every other
    file look hand-edited). Returns whether version.json was rewritten."""
    info = remote_version_info(c, app_id, known_paths=remote_file_paths(c, app_id))
    if not isinstance(info.get(PUSH_MANIFEST_KEY), dict):
        return False
    info[PUSH_MANIFEST_KEY] = {**info[PUSH_MANIFEST_KEY], **hashes}
    c.call("POST", f"/api/v1/apps/{app_id}/files/static/version.json",
           base64.b64encode(json.dumps(info).encode()).decode())
    return True


def bootstrap_schema_probe(c, m: dict, a, app: dict, app_id: str, clock=time.monotonic,
                           sleep=time.sleep) -> tuple[str, str]:
    """Put the schema probe on an app that has none (or an older one) and read the schema through it. Touches ONLY the
    probe files and the `schema` hook definition (plus static/version.json's push manifest, and the dependency step when
    pg is not installed): never other hooks, static files or running hooks' code. Guards those files for hand edits
    first. Returns ('PASS'|'FAIL'|'SKIP'|'DRIFT', text). Not rolled back if the full install later stops."""
    listed = {f.get("path") for f in app.get("files") or [] if isinstance(f, dict)}
    paths = list(PROBE_FILES)
    if "/package.json" in m["files"] and "/package.json" not in listed:
        paths.insert(0, "/package.json")      # no dependency list on the box at all: the probe needs pg from it
    if not has_probe_hook(app) and getattr(a, "skip_hooks", False):
        return "FAIL", probe_cannot_run("--skip-hooks leaves the schema hook unregistered")
    if guard_pushed_files(c, m, getattr(a, "force", False), getattr(a, "save_remote", None), only=set(paths)):
        return "DRIFT", ""
    print("install: bootstrapping the schema probe (" + ", ".join(paths) + " and the schema hook only)")
    known = remote_file_paths(c, app_id)
    pushed: dict[str, str] = {}
    for p in paths:
        data = deploy_bytes(m, m["files"][p])
        if c.read_file(app_id, p, known_paths=known) != data:
            c.call("POST", f"/api/v1/apps/{app_id}/files{p}", base64.b64encode(data).decode())
            print(f"wrote {p} ({len(data)} bytes)")
        pushed[p] = sha256_hex(data)
    if not getattr(a, "skip_deps", False) and not deps_present(c, app_id, [PROBE_DEP]):
        report_deps(install_deps(c, m, clock, sleep), app_id)     # the full install's dependency step
    c.call("POST", f"/api/v1/apps/{app_id}/hooks", next(h for h in m["hooks"] if h.get("id") == PROBE_HOOK_ID))
    print(f"updated hook {PROBE_HOOK_ID}")
    if record_in_push_manifest(c, app_id, pushed):
        print("recorded the probe files in the box's push manifest")
    got = probe_run(c, app_id, clock, sleep)
    if got is None:      # a runtime may cache hook modules: restart once, then ask again
        try:
            c.call("PATCH", f"/api/v1/apps/{app_id}/restart", {})
        except SystemExit:
            pass
        got = probe_run(c, app_id, clock, sleep)
    if got is None:
        return "FAIL", probe_cannot_run("the schema hook did not start or gave no answer")
    if got.get("skipped"):
        return "SKIP", ""
    if "installed" not in got:
        err = str(got.get("error") or "unknown error")
        if "pg not installed" in err:
            return "FAIL", probe_cannot_run("the pg package is not installed in the app")
        return "FAIL", f"the NF-side schema probe could not read the Timescale schema: {err[:200]}. " + PROBE_LEFTOVER
    lvl, text = probe_verdict(got)
    if lvl == "PASS":
        return lvl, text + "; the probe was bootstrapped first"
    return lvl, text + ". " + PROBE_LEFTOVER


def install_schema_gate(c, m: dict, a, prior: dict | None, app_id: str, environ, clock=time.monotonic,
                        sleep=time.sleep, dry_run: bool = False) -> tuple[str, str, bool]:
    """(level, text, bootstrapped) for the install's Timescale schema check. level: SKIP (Lite / no Timescale / no app),
    PASS, FAIL, DRIFT (a probe file was hand-edited), DRYRUN (a bootstrap would be needed; nothing was written).
    The probe on the box is used when it is current; an app with no `schema` hook, or one whose probe reports an older
    required schema than this release, gets the probe bootstrapped first. A manifest that ships no probe keeps the
    DSN/psql path. Never falls back to psql on its own when the probe cannot run."""
    if not prior or not timescale_selected(prior):
        return "SKIP", "", False
    if not manifest_ships_probe(m):
        lvl, text = schema_preflight(c, prior, app_id, environ)
        return lvl, text, False
    if has_probe_hook(prior):
        got = probe_run(c, app_id, clock, sleep)
        if got is None:                  # hook there but no usable answer: the explicit DSN path, as before
            lvl, text = timescale_schema_check(prior, environ)
            return lvl, text, False
        want, have = local_required_schema(m), got.get("required")
        if not (isinstance(have, int) and want is not None and have < want):
            lvl, text = probe_verdict(got)
            return lvl, text, False
        why = f"the installed probe checks schema {have}, this release needs {want}"
    else:
        why = "the installed app has no schema probe"
    if dry_run:
        if guard_pushed_files(c, m, getattr(a, "force", False), getattr(a, "save_remote", None), only=set(PROBE_FILES)):
            return "DRIFT", "", False
        return "DRYRUN", (f"would bootstrap the schema probe ({why}): push {', '.join(PROBE_FILES)} and register the "
                          f"{PROBE_HOOK_ID} hook, then read the schema through it"), False
    print(f"install: {why}; bootstrapping it")
    lvl, text = bootstrap_schema_probe(c, m, a, prior, app_id, clock, sleep)
    return lvl, text, lvl != "DRIFT"


def schema_preflight(c, app: dict, app_id: str, environ=None, **kw) -> tuple[str, str]:
    """Schema check order: the NF-side probe when the installed app has it, else the NF_TIMESCALE_PREFLIGHT_DSN path
    (psql), else a refusal that names both remedies. SKIP on Lite or a non-Timescale engine."""
    if not timescale_selected(app):
        return "SKIP", ""
    probed = schema_probe(c, app, app_id)
    if probed is not None:
        return probed
    return timescale_schema_check(app, environ, **kw)


def timescale_schema_check(app: dict, environ=None, runner=subprocess.run) -> tuple[str, str]:
    """Read-only preflight against the configured Timescale database, with no credentials in argv/output."""
    env = os.environ if environ is None else environ
    engine = str(option_scalar(app, "engine") or "auto").strip().lower()
    raw = option_scalar(app, "timescale")
    explicit = engine == "timescale"
    configured = raw is not None and str(raw).strip() != ""
    if engine in {"sqlite", "pglite"} or (not explicit and not configured):
        return "SKIP", ""
    dsn_override = env.get("NF_TIMESCALE_PREFLIGHT_DSN")
    if not dsn_override and is_loopback_host(timescale_connection_host(raw)):
        return "FAIL", ("Timescale hook host is loopback from the NF host's perspective; this CLI cannot assume "
                         "the same loopback. Set NF_TIMESCALE_PREFLIGHT_DSN to a forwarded or reachable DB endpoint, "
                         "or install a release with the NF-side schema probe (the `schema` hook), which needs no DB route")
    conn = dsn_override or raw
    if not conn:
        return "FAIL", ('Timescale is selected but no connection is available; set NF_TIMESCALE_PREFLIGHT_DSN '
                         'for a read-only schema check')
    password_env = None
    configured_password = None
    ssl_config = None
    if isinstance(conn, str) and conn.lstrip().startswith("{"):
        try:
            obj = json.loads(conn)
        except ValueError:
            obj = None
        password_env = obj.get("passwordEnv") if isinstance(obj, dict) else None
        configured_password = obj.get("password") if isinstance(obj, dict) else None
        ssl_config = obj.get("ssl") if isinstance(obj, dict) else None
        conn = obj.get("connectionString") if isinstance(obj, dict) else None
        if not conn and isinstance(obj, dict) and obj.get("host"):
            # Use libpq environment variables so passwords never appear in process arguments.
            pg = {"PGHOST": str(obj["host"])}
            for key, var in (("port", "PGPORT"), ("user", "PGUSER"),
                             ("password", "PGPASSWORD"), ("sslmode", "PGSSLMODE")):
                if obj.get(key) is not None:
                    pg[var] = str(obj[key])
            pg["PGDATABASE"] = str(obj.get("database") or "postgres")
            conn = pg
    if isinstance(conn, str):
        try:
            u = urllib.parse.urlparse(conn)
            if u.scheme.lower() in ("postgres", "postgresql") and u.hostname:
                pg = {"PGHOST": u.hostname}
                if u.port: pg["PGPORT"] = str(u.port)
                if u.path and u.path != "/": pg["PGDATABASE"] = urllib.parse.unquote(u.path[1:])
                if u.username: pg["PGUSER"] = urllib.parse.unquote(u.username)
                if u.password: pg["PGPASSWORD"] = urllib.parse.unquote(u.password)
                q = urllib.parse.parse_qs(u.query)
                if q.get("sslmode"): pg["PGSSLMODE"] = q["sslmode"][0]
                for key, var in (("sslrootcert", "PGSSLROOTCERT"), ("sslcert", "PGSSLCERT"), ("sslkey", "PGSSLKEY")):
                    if q.get(key): pg[var] = q[key][0]
                conn = pg
            elif "=" in conn:
                import shlex
                pg = {}
                keys = {"host": "PGHOST", "port": "PGPORT", "dbname": "PGDATABASE", "database": "PGDATABASE",
                        "user": "PGUSER", "password": "PGPASSWORD", "sslmode": "PGSSLMODE",
                        "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY"}
                for item in shlex.split(conn):
                    key, sep, value = item.partition("=")
                    if not sep or key not in keys:
                        return "FAIL", "Timescale connection setting is not a supported PostgreSQL DSN (value not shown)"
                    pg[keys[key]] = value
                conn = pg
            else:
                return "FAIL", "Timescale connection setting is not a supported PostgreSQL URL (value not shown)"
        except ValueError:
            return "FAIL", "Timescale connection setting is malformed (value not shown)"
    if isinstance(conn, dict):
        pg = conn
    else:
        return "FAIL", "Timescale connection setting is not usable for the read-only schema check (value not shown)"
    psql = shutil.which("psql")
    if not psql:
        return "FAIL", ("psql is unavailable; to verify the Timescale schema version " + SCHEMA_REMEDY)
    inherited_allowlist = ("PATH", "SystemRoot", "WINDIR", "HOME", "USERPROFILE", "TMP", "TEMP")
    child_env = {k: os.environ[k] for k in inherited_allowlist if k in os.environ}
    child_env.update({k: env[k] for k in inherited_allowlist if k in env})
    child_env.update(pg)
    ssl_enabled = isinstance(ssl_config, (dict, list)) or bool(ssl_config)
    if (not dsn_override and isinstance(ssl_config, dict)
            and any(ssl_config.get(k) for k in ("ca", "cert", "key"))):
        return "FAIL", ("Timescale hook TLS uses custom certificate material that this preflight cannot mirror; "
                         "use the protected DSN/certificate procedure documented for the installer")
    if ssl_enabled:
        # The hook explicitly asks for TLS; never let libpq silently probe with plaintext.
        child_env["PGSSLMODE"] = ("require" if isinstance(ssl_config, dict)
                                  and ssl_config.get("rejectUnauthorized") is False else "verify-full")
    if configured_password:
        child_env["PGPASSWORD"] = str(configured_password)
    if password_env:
        password_name = str(password_env)
        password = env[password_name] if password_name in env else os.environ.get(password_name)
        if not password:
            return "FAIL", "configured Timescale password environment variable is unavailable; set NF_TIMESCALE_PREFLIGHT_DSN instead"
        child_env["PGPASSWORD"] = password
    sql = "SELECT value #>> '{}' FROM openfdd.config WHERE key='schema_version'"
    try:
        proc = runner([psql, "-X", "-w", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1",
                       "-c", "BEGIN TRANSACTION READ ONLY", "-c", sql, "-c", "ROLLBACK"],
                      env=child_env, capture_output=True, text=True, timeout=10)
    except Exception:
        return "FAIL", "could not connect to Timescale for a read-only schema check (connection details redacted)"
    if proc.returncode:
        return "FAIL", "Timescale schema is missing or unreachable (connection details redacted); run nf-app/timescale/install.sql as installer/owner"
    vals = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    try:
        got = int(vals[-1]) if vals else 0
    except ValueError:
        got = 0
    if got != 3:
        return "FAIL", f"Timescale schema version {got}; this release requires 3. Run nf-app/timescale/install.sql as installer/owner"
    return "PASS", "Timescale schema version 3"


def hand_edit_line(drift: dict) -> tuple[str, str, str]:
    """(level, what, text) for doctor: files on the box that differ from the last push (read-only)."""
    if drift["baseline"] == "none":
        return "PASS", "hand edits", "nothing installed to compare"
    names = drift["drifted"]
    shown = ", ".join(names[:10]) + (f", ... (+{len(names) - 10} more)" if len(names) > 10 else "")
    if not names:
        return "PASS", "hand edits", f"none ({drift['checked']} files match {baseline_text(drift)})"
    if drift["baseline"] == "manifest":
        return "WARN", "hand edits", (f"{len(names)} file(s) on the box differ from what was last pushed (edited by hand): "
                                      f"{shown}. The next push/install stops until you pass --force "
                                      "(--save-remote DIR keeps the box copies first)")
    return "WARN", "hand edits", (f"no push manifest on the box (older release): {len(names)} file(s) differ from "
                                  f"{baseline_text(drift)}: {shown}. The next push/install stops until you pass --force "
                                  "(--save-remote DIR keeps the box copies first)")


def cmd_doctor(c, m: dict, now: datetime.datetime | None = None, environ=None) -> int:
    app_id = m["application"]["id"]
    bad = 0

    def line(level: str, what: str, text: str) -> None:
        nonlocal bad
        bad += level == "FAIL"
        _safe_print(f"[{level}] {what}: {text}")

    try:
        apps = {a["id"]: a for a in c.apps()}
    except SystemExit as e:
        # the failure's own category (connectivity / tls / auth / http); a bare error falls back on its HTTP status
        status = getattr(e, "status", 0)
        line("FAIL", getattr(e, "kind", "") or ("auth" if status in (401, 403) else "console"), str(e))
        return 1
    line("PASS", "auth", "console login accepted (Caddy and NF both let it through)")
    a = apps.get(app_id)
    if not a:
        line("FAIL", "app", f"{app_id} is not installed")
        return 1
    want = version_info(m["_dir"])["version"]
    raw = None
    try:
        raw = c.read_file(app_id, "/static/version.json")
    except SystemExit:
        pass
    try:
        got = json.loads(raw.decode()).get("version") if raw else None
    except ValueError:
        got = None
    opt = option_value(a, "version")
    line("PASS" if got == want else "FAIL", "version",
         f"installed {got or 'unknown'} (setting {opt or 'unset'}), repo {want}")
    names = declared_deps(m)
    if names:
        here = deps_present(c, app_id, names)
        if len(here) == len(names):
            line("PASS", "deps", f"present: {', '.join(names)}")
        elif not here:
            line("WARN", "deps", f"not visible through the file API ({', '.join(names)}); a hook run shows whether "
                                 f"they are installed. {manual_deps_hint(app_id)}")
        else:
            line("FAIL", "deps", f"missing: {', '.join(n for n in names if n not in here)}. {manual_deps_hint(app_id)}")
    else:
        line("PASS", "deps", "none declared")
    for h in a.get("hooks", []):
        try:
            runs = c.call("GET", f"/api/v1/apps/{app_id}/hooks/{h['id']}/runs?page_size=1&include_results=true")
        except SystemExit as e:
            line("WARN", f"hook {h['id']}", f"could not read runs ({e})")
            continue
        last = (runs.get("runs") or [None])[0]
        if not last:
            line("PASS" if h.get("mode") == ON_REQUEST else "WARN", f"hook {h['id']}", "never run")
            continue
        text = run_error_text(last)
        if last.get("state") == "STATE_SUCCESS" and not result_failure(last):
            line("PASS", f"hook {h['id']}", f"last run {last['state']}")
        elif h.get("mode") == ON_REQUEST and last.get("state") == "STATE_SUCCESS":
            line("WARN", f"hook {h['id']}", f"last run returned ok:false ({result_failure(last)}), usually missing args")
        else:
            line("FAIL", f"hook {h['id']}", f"last run {last.get('state')}: "
                 f"{(result_failure(last) or text or '')[:160].strip()}")
        if h["id"] == "fdd" and (unit_skips := fdd_unit_skip_text(last)):
            line("WARN", "fdd units", unit_skips)
    if any("weather" in h["entryPoint"] or "open_meteo" in h["entryPoint"] for h in m["hooks"]):
        lvl, text = weather_coords_source(c, a)
        line("PASS" if lvl == "pass" else "FAIL", "weather coords", text)
    lvl, text = timezone_source(c, a)
    line(lvl.upper(), "timezone", text)
    fdd_def = next((h for h in a.get("hooks", []) if h.get("id") == "fdd"), None)
    fdd_man = next((h for h in m["hooks"] if h.get("id") == "fdd"), None)
    if fdd_def or fdd_man:
        rule = ((fdd_def or {}).get("schedule") or {}).get("rrule") or ((fdd_man or {}).get("schedule") or {}).get("rrule")
        try:
            lvl, text = fdd_freshness(c, rrule_interval_seconds(rule) or DEFAULT_FDD_INTERVAL,
                                      now or datetime.datetime.now(datetime.timezone.utc))
        except SystemExit as e:
            lvl, text = "warn", f"could not read the points to compare ages ({e})"
        line(lvl.upper(), "fdd freshness", text)
    lvl, text = timescale_check(a)
    line(lvl, "timescale", text)
    if timescale_selected(a) and manifest_ships_probe(m) and not has_probe_hook(a):
        line("WARN", "timescale schema", "schema probe not installed yet; install will bootstrap it")
    else:
        schema_lvl, schema_text = schema_preflight(c, a, app_id, environ)
        line(schema_lvl, "timescale schema", schema_text or "not selected (Lite/sqlite/pglite)")
    try:
        drift = find_drift(c, m)
    except SystemExit as e:
        line("WARN", "hand edits", f"could not compare the files on the box ({e})")
    else:
        line(*hand_edit_line(drift))
    code, headers = c.probe("/")
    target = f"/api/v1/apps/static/{app_id}/"
    if code in (301, 302, 303, 307, 308):
        loc = urllib.parse.urlparse(headers.get("Location", "")).path
        line("PASS" if loc.rstrip("/") == target.rstrip("/") else "FAIL", "/ redirect",
             f"{code} -> {loc or '(none)'}" + ("" if loc.rstrip("/") == target.rstrip("/") else f", expected {target}"))
    elif code:
        line("WARN", "/ redirect", f"HTTP {code}, no redirect (fine unless a front door should send / to the app)")
    else:
        line("WARN", "/ redirect", "not reachable without login")
    print("doctor: " + ("all checks passed" if not bad else f"{bad} check(s) failed"))
    return 1 if bad else 0


# ---------------------------------------------------------------- cli

def parse_args(pairs: list[str] | None) -> dict[str, str]:
    """--arg KEY=VALUE (repeatable) -> StartHook string map."""
    out: dict[str, str] = {}
    for p in pairs or []:
        k, sep, v = p.partition("=")
        if not sep or not k:
            raise SystemExit(f"--arg needs KEY=VALUE, got {p!r}")
        out[k] = v
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Sync, install and check an NF app manifest on an NF console (local console login required)")
    ap.add_argument("--env", type=Path, default=Path("~/.secrets/nf_site_console.env"),
                    help="env file with CONSOLE_USERNAME, CONSOLE_PASSWORD, NF_CONSOLE_URL (optional NF_CA_FILE)")
    ap.add_argument("--console", help="console base URL (default NF_CONSOLE_URL from --env)")
    ap.add_argument("--ca-file", metavar="FILE",
                    help="PEM file to trust in addition to the system CAs (default NF_CA_FILE); for a self-signed front door")
    ap.add_argument("--pin-server-cert", action="store_true",
                    help="fetch the certificate the server presents, print its SHA-256 and trust only it for this run "
                         "(its SAN must match the host); verification stays on")
    ap.add_argument("action", choices=["status", "push", "run", "pull", "diff", "install", "uninstall", "remove-old", "doctor"])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--skip-hooks", action="store_true",
                    help="push/install: write files only, leave hook definitions alone (e.g. a bench that already runs them)")
    ap.add_argument("--skip-deps", action="store_true",
                    help="push/install: do not install package.json dependencies (PATCH /api/v1/apps/<id>/dependencies)")
    ap.add_argument("--force", action="store_true",
                    help="push/install: overwrite files on the box that were edited by hand (default: stop and list them)")
    ap.add_argument("--save-remote", type=Path, metavar="DIR",
                    help="push/install: first download the hand-edited box copies to DIR (same folder layout) for review")
    ap.add_argument("--dry-run", action="store_true",
                    help="install: run the read-only checks (login, schema probe, hand edits) and say what would happen, "
                         "e.g. \"would bootstrap the schema probe\"; writes nothing")
    ap.add_argument("--skip-verify-run", action="store_true",
                    help="install: do not run the scheduled hooks once to verify")
    ap.add_argument("--remove-old", action="store_true",
                    help="install: delete the predecessor apps listed under `replaces` in the manifest "
                         "(dry run: only lists them, plus orphan points, unless --yes)")
    ap.add_argument("--yes", action="store_true", help="remove-old / uninstall: actually delete (default is a dry run)")
    ap.add_argument("--wait", type=float, metavar="SECONDS",
                    help="run: how long to wait for each run (default: the hook's invokeTimeout + 60 s). "
                         "On timeout the run is reported as still running (exit 3) and is never re-started")
    ap.add_argument("--resume", type=int, metavar="PID",
                    help="run: wait on this existing run of the one --hook instead of starting a new one")
    ap.add_argument("--hook", action="append", dest="hooks", metavar="ID",
                    help="push/run: only these hook ids (repeatable); run starts them even if on-request")
    ap.add_argument("--arg", action="append", dest="hook_args", metavar="KEY=VALUE",
                    help="run: StartHook argument (repeatable); on-request hooks are only started by a blanket run "
                         "when at least one --arg is given")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.env.expanduser().is_file():
        env = load_env(a.env)
        if not env.get("NF_TIMESCALE_PREFLIGHT_DSN") and os.environ.get("NF_TIMESCALE_PREFLIGHT_DSN"):
            env["NF_TIMESCALE_PREFLIGHT_DSN"] = os.environ["NF_TIMESCALE_PREFLIGHT_DSN"]
    else:
        env = {k: v for k, v in os.environ.items() if k.startswith(("NF_", "CONSOLE_"))}
        if not env:
            raise SystemExit(f"env file {a.env} not found (and no NF_/CONSOLE_ variables in the environment)")
    problem = env_problem({**env, **({"NF_CONSOLE_URL": a.console} if a.console else {})}, str(a.env))
    if problem:
        raise SystemExit(problem)
    console = a.console or env["NF_CONSOLE_URL"]
    ca = a.ca_file or env.get("NF_CA_FILE")
    if a.pin_server_cert:
        ctx, fp = pin_server_cert(console)
        print(f"pinned server certificate sha256={fp}")
    else:
        ctx = make_ssl_context(ca)
    c = Console(console, env["CONSOLE_USERNAME"], env["CONSOLE_PASSWORD"], ctx)
    m = manifest(a.manifest)
    a._environ = env
    if a.action == "status":
        return cmd_status(c, m)
    if a.action == "push":
        return cmd_push(c, m, a.skip_hooks, a.hooks, a.skip_deps, force=a.force, save_remote=a.save_remote)
    if a.action == "run":
        return cmd_run(c, m, a.hooks, a.wait, a.resume, args=parse_args(a.hook_args) or None)
    if a.action == "install":
        return cmd_install(c, m, a)
    if a.action == "uninstall":
        return cmd_uninstall(c, m, a.yes)
    if a.action == "remove-old":
        return cmd_remove_old(c, m, a.yes)
    if a.action == "doctor":
        return cmd_doctor(c, m, environ=env)
    return cmd_pull(c, m, write=(a.action == "pull"))


if __name__ == "__main__":
    sys.exit(main())
