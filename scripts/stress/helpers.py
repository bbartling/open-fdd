"""HTTP helpers for Open-FDD Soft-OPEN stress gate (SPARQL + FDD).

Port of the BPS ``scripts/stress/helpers.py`` connection style so a Windows
laptop on the LAN can target a lab Open-FDD central:

  python scripts/stress/run_gate.py --host <lab-ip>
  python scripts/stress/01_sparql_model.py --host <lab-ip>

Open-FDD differences vs BPS (same scientific lesson):
  - Default port **8080** (BPS lab often 8090)
  - JWT via ``POST /api/auth/login`` → ``token`` or ``access_token``
  - SPARQL at ``POST /api/model/sparql`` (needs ``building_id`` + ``query`` or ``query_id``)
  - Package TTL at ``GET /api/csv/import/package/mapping/ttl`` (and haystack.ttl)
  - BPS-compatible ``GET /api/model/ttl`` (Haystack projection) + ``PUT /api/model/semantic-meta``
    + ``GET /api/model/agent-context``
  - Timeseries via ``GET /api/timeseries/readings`` / ``GET|POST /api/historian/query``

Env (optional): OPENFDD_STRESS_BASE / OPENFDD_API_BASE, OPENFDD_STRESS_USER,
OPENFDD_STRESS_PASS / OPENFDD_AGENT_PASSWORD / OPENFDD_ADMIN_PASSWORD,
OPENFDD_STRESS_BUILDING_ID.

Synthetic sites only — never hardcode private consumer campus names.
"""

from __future__ import annotations

import argparse
import json
import os
import math
import sys
import time
import hashlib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PORT = 8080
DEFAULT_LOCAL = f"http://127.0.0.1:{DEFAULT_PORT}"
DEFAULT_USER = (
    os.environ.get("OPENFDD_STRESS_USER")
    or os.environ.get("OPENFDD_USER")
    or "agent"
)
DEFAULT_PASS = (
    os.environ.get("OPENFDD_STRESS_PASS")
    or os.environ.get("OPENFDD_AGENT_PASSWORD")
    or os.environ.get("OPENFDD_ADMIN_PASSWORD")
    or ""
)
# Caller-supplied synthetic building; gates must not invent private campus ids.
DEFAULT_BUILDING_ID = (
    os.environ.get("OPENFDD_STRESS_BUILDING_ID")
    or os.environ.get("OPENFDD_BUILDING_ID")
    or ""
)


def configure_stdio() -> None:
    """Best-effort UTF-8 for Windows consoles (cp1252 otherwise crashes on arrows)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


configure_stdio()


def safe_print(*args: Any, **kwargs: Any) -> None:
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        text = " ".join(str(a) for a in args)
        text = text.encode(enc, errors="replace").decode(enc, errors="replace")
        print(text, **{k: v for k, v in kwargs.items() if k != "file"})


def resolve_base_url(
    *,
    base_url: str | None = None,
    host: str | None = None,
    port: int = DEFAULT_PORT,
) -> str:
    """Explicit URL > --host > env OPENFDD_STRESS_BASE/OPENFDD_API_BASE > localhost."""
    if base_url:
        return base_url.rstrip("/")
    if host:
        h = host.strip().rstrip("/")
        if h.startswith("http://") or h.startswith("https://"):
            return h.rstrip("/")
        return f"http://{h}:{port}"
    env = os.environ.get("OPENFDD_STRESS_BASE") or os.environ.get("OPENFDD_API_BASE")
    if env:
        return env.rstrip("/")
    return DEFAULT_LOCAL


DEFAULT_BASE = resolve_base_url()


def apply_base_url(base: str) -> str:
    """Set process env so child imports see the chosen API root."""
    global DEFAULT_BASE
    base = base.rstrip("/")
    DEFAULT_BASE = base
    os.environ["OPENFDD_STRESS_BASE"] = base
    return base


def add_connection_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--base-url",
        default=None,
        help=f"Full API root (default: env or {DEFAULT_LOCAL})",
    )
    ap.add_argument(
        "--host",
        default=None,
        help="Remote hostname/IP only — builds http://HOST:8080 "
        "(Windows laptop → lab: --host <lab-ip>)",
    )
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port with --host")
    ap.add_argument("--user", default=DEFAULT_USER, help="Open-FDD login username")
    ap.add_argument(
        "--password",
        default=DEFAULT_PASS,
        help="Open-FDD login password (env OPENFDD_AGENT_PASSWORD preferred)",
    )
    ap.add_argument(
        "--building-id",
        default=DEFAULT_BUILDING_ID or None,
        help="Synthetic building_id for SPARQL/TTL/FDD scope "
        "(env OPENFDD_STRESS_BUILDING_ID)",
    )


def parse_connection(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(add_help=False)
    add_connection_args(ap)
    args, _unknown = ap.parse_known_args(argv)
    args.base_url = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    return args


def short(value: str) -> str:
    if not value:
        return ""
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A scan/login redirect must never forward a bearer to another origin.
        return None


class HttpClient:
    """Minimal urllib client with BPS-like ``base_url`` + timeout."""

    def __init__(self, base_url: str, *, timeout: float = 120.0,
                 max_requests: int = 500, max_response_bytes: int = 32 * 1024 * 1024) -> None:
        self.base_url = base_url.rstrip("/")
        origin = urlsplit(self.base_url)
        if (origin.scheme not in {"http", "https"} or not origin.hostname
                or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in {"", "/"}):
            raise ValueError("stress base must be an http(s) origin without credentials or path")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if max_requests < 1 or max_response_bytes < 1:
            raise ValueError("request and response budgets must be positive")
        self.timeout = timeout
        self.max_requests = max_requests
        self.max_response_bytes = max_response_bytes
        self.requests_sent = 0
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        if not math.isfinite(timeout or self.timeout) or (timeout is not None and timeout <= 0):
            raise ValueError("timeout must be finite and positive")
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        parsed = urlsplit(url)
        target = urlsplit(self.base_url)
        if (parsed.scheme, parsed.hostname, parsed.port) != (target.scheme, target.hostname, target.port):
            raise ValueError("stress request escaped the configured origin")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("request URLs must not embed credentials or fragments")
        if self.requests_sent >= self.max_requests:
            raise RuntimeError("stress request budget exhausted before transmission")
        if params:
            q = urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{q}" if q else url
        data: bytes | None = None
        hdrs = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
        try:
            self.requests_sent += 1
            with self._opener.open(req, timeout=timeout or self.timeout) as resp:
                body = resp.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise RuntimeError("stress response exceeded byte budget")
                return int(resp.status), {k.lower(): v for k, v in resp.headers.items()}, body
        except urllib.error.HTTPError as e:
            body = e.read(self.max_response_bytes + 1) if e.fp else b""
            if len(body) > self.max_response_bytes:
                raise RuntimeError("stress error response exceeded byte budget") from None
            return int(e.code), {k.lower(): v for k, v in e.headers.items()}, body

    def get_json(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        status, _hdrs, raw = self.request(
            "GET", path, headers=headers, params=params, timeout=timeout
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"GET {path} -> HTTP {status}")
        return json.loads(raw.decode("utf-8") or "null")

    def post_json(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        timeout: float | None = None,
    ) -> Any:
        status, _hdrs, raw = self.request(
            "POST", path, headers=headers, json_body=json_body, timeout=timeout
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"POST {path} -> HTTP {status}")
        return json.loads(raw.decode("utf-8") or "null")

    def get_text(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, dict[str, str]]:
        status, hdrs, raw = self.request(
            "GET", path, headers=headers, params=params, timeout=timeout
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"GET {path} -> HTTP {status}")
        return raw.decode("utf-8", errors="replace"), hdrs


def client(base_url: str | None = None) -> HttpClient:
    return HttpClient((base_url or DEFAULT_BASE).rstrip("/"), timeout=120.0)


def wait_until_ready(http: HttpClient, *, timeout_s: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            status, _hdrs, raw = http.request("GET", "/api/health", timeout=15.0)
            if status == 200:
                body = json.loads(raw.decode("utf-8") or "{}")
                # Open-FDD OkHealthResponse always includes ok=true when healthy.
                if isinstance(body, dict) and body.get("ok") is True:
                    expected = os.environ.get("OPENFDD_STRESS_EXPECT_VERSION")
                    if expected and body.get("version") != expected:
                        raise RuntimeError("candidate version does not match --expected-version")
                    _OBSERVATIONS["observed_version"] = body.get("version")
                    safe_print(f"GET /api/health -> ok (attempt {attempt})")
                    return body
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            safe_print(f"waiting for API... attempt {attempt} ({type(exc).__name__})")
        if time.monotonic() >= deadline:
            raise SystemExit(
                f"API not ready within {timeout_s:.0f}s at {http.base_url}\n"
                "  Tip: on the lab box run ./scripts/openfdd_stack_up.sh portal\n"
                "  From Windows/LAN: python scripts/stress/run_gate.py --host <lab-ip>"
            )
        time.sleep(2.0)


def login(
    http: HttpClient,
    *,
    user: str | None = None,
    password: str | None = None,
) -> dict[str, str]:
    user = user or DEFAULT_USER
    password = password if password is not None else DEFAULT_PASS
    if not password:
        raise SystemExit(
            "login password required: pass --password or set OPENFDD_AGENT_PASSWORD "
            "(or OPENFDD_STRESS_PASS / OPENFDD_ADMIN_PASSWORD)"
        )
    status, _hdrs, raw = http.request(
        "POST",
        "/api/auth/login",
        json_body={"username": user, "password": password},
        timeout=30.0,
    )
    if not 200 <= status < 300:
        raise SystemExit(f"login failed HTTP {status}")
    body = json.loads(raw.decode("utf-8") or "{}")
    token = body.get("token") or body.get("access_token")
    if not token:
        raise SystemExit("login response missing token")
    return {"Authorization": f"Bearer {token}"}


def post_sparql(
    http: HttpClient,
    headers: dict[str, str],
    *,
    building_id: str,
    query: str | None = None,
    query_id: str | None = None,
    equipment_id: str | None = None,
) -> list[dict[str, str]]:
    """POST /api/model/sparql — free-form ``query`` or template ``query_id``.

    Tip Soft-OPEN (C13) accepts read-only SELECT/ASK free-form with building_id.
    Template path returns typed bindings; free-form returns ``rows`` (v2 typed
    SPARQL JSON Results terms) / ASK boolean.
    """
    if not building_id:
        raise SystemExit("building_id required for POST /api/model/sparql")
    body: dict[str, Any] = {"building_id": building_id}
    if query_id:
        body["query_id"] = query_id
    if query:
        body["query"] = query
    if equipment_id:
        body["equipment_id"] = equipment_id
    if "query" not in body and "query_id" not in body:
        raise SystemExit("post_sparql requires query or query_id")

    status, _hdrs, raw = http.request(
        "POST", "/api/model/sparql", headers=headers, json_body=body
    )
    if not 200 <= status < 300:
        raise RuntimeError(f"POST /api/model/sparql -> HTTP {status}")
    payload = json.loads(raw.decode("utf-8") or "{}")
    if (not isinstance(payload, dict) or payload.get("ok") is False
            or payload.get("truncated") is True
            or any(isinstance(payload.get(k), dict) and payload[k].get("truncated") is True
                   for k in ("meta", "results"))):
        raise RuntimeError("SPARQL response failed or was truncated")
    return _normalize_sparql_rows(payload)


def _normalize_sparql_rows(payload: Any) -> list[dict[str, str]]:
    """Accept tip free-form shape, template bindings, or sparql-playground nesting."""
    if not isinstance(payload, dict):
        return []

    # Free-form wrapper: { ok, results: { kind, rows|boolean, ... }, meta }
    results = payload.get("results")
    if isinstance(results, dict):
        if "boolean" in results:
            return [{"ask": str(results["boolean"])}]
        if isinstance(results.get("rows"), list):
            return [_stringify_row(r) for r in results["rows"] if isinstance(r, dict)]
        # Nested sparql-json: results.results.bindings
        inner = results.get("results")
        if isinstance(inner, dict) and isinstance(inner.get("bindings"), list):
            return [_from_sparql_json_binding(b) for b in inner["bindings"]]

    # Flat free-form body (execute_readonly_on_snapshot): { kind, rows, boolean }
    if "boolean" in payload and payload.get("kind") == "ask":
        return [{"ask": str(payload["boolean"])}]
    if isinstance(payload.get("rows"), list):
        return [_stringify_row(r) for r in payload["rows"] if isinstance(r, dict)]

    # Template bindings: equipment[].points[]
    equipment = payload.get("equipment")
    if isinstance(equipment, list):
        rows: list[dict[str, str]] = []
        for eq in equipment:
            if not isinstance(eq, dict):
                continue
            eid = str(eq.get("equipment_id") or "")
            for pt in eq.get("points") or []:
                if not isinstance(pt, dict):
                    continue
                rows.append(
                    {
                        "equipmentId": eid,
                        "pointId": str(pt.get("point_id") or ""),
                        "column": str(pt.get("column") or ""),
                        "canonicalRole": str(pt.get("canonical_role") or ""),
                    }
                )
            if not eq.get("points"):
                rows.append(
                    {
                        "equipmentId": eid,
                        "equipType": str(eq.get("equip_type") or ""),
                    }
                )
        return rows

    return []


def _stringify_row(row: dict[str, Any]) -> dict[str, str]:
    """Flatten free-form SPARQL rows.

    Soft-OPEN ``ofdd_sparql_readonly_v2`` emits W3C SPARQL JSON Results terms
    ``{type,value,datatype?,xml:lang?}``; older v1 rows were plain strings.
    """
    out: dict[str, str] = {}
    for k, v in row.items():
        if isinstance(v, dict) and "value" in v:
            out[k] = "" if v.get("value") is None else str(v.get("value"))
        else:
            out[k] = "" if v is None else str(v)
    return out


def _from_sparql_json_binding(binding: Any) -> dict[str, str]:
    if not isinstance(binding, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in binding.items():
        if isinstance(v, dict):
            out[k] = str(v.get("value") or "")
        else:
            out[k] = str(v)
    return out


def get_package_ttl(
    http: HttpClient,
    headers: dict[str, str],
    *,
    building_id: str,
    haystack: bool = False,
    model_alias: bool = False,
) -> tuple[str, dict[str, str]]:
    """Fetch package mapping TTL (Open-FDD product path).

    ``model_alias=True`` → ``GET /api/model/ttl`` (BPS-compatible Soft-OPEN alias)
    ``haystack=False`` → ``/api/csv/import/package/mapping/ttl``
    ``haystack=True``  → ``/api/csv/import/package/mapping/haystack.ttl``
    """
    if not building_id:
        raise SystemExit("building_id required for package TTL")
    if model_alias:
        path = "/api/model/ttl"
    elif haystack:
        path = "/api/csv/import/package/mapping/haystack.ttl"
    else:
        path = "/api/csv/import/package/mapping/ttl"
    return http.get_text(path, headers=headers, params={"building_id": building_id})


def get_sparql_catalog(http: HttpClient, headers: dict[str, str]) -> dict[str, Any]:
    return http.get_json("/api/model/sparql/predefined", headers=headers)


def get_timeseries_readings(
    http: HttpClient,
    headers: dict[str, str],
    *,
    site_id: str,
    columns: str,
    hours: int | None = None,
    all_rows: bool = False,
) -> dict[str, Any]:
    """GET /api/timeseries/readings — Open-FDD chart/readings path.

    ``columns`` is comma-separated ``equipment_id:column`` or bare column keys.
    """
    params: dict[str, Any] = {"site_id": site_id, "columns": columns}
    if all_rows:
        params["all"] = "true"
    elif hours is not None:
        params["hours"] = hours
    return http.get_json("/api/timeseries/readings", headers=headers, params=params)


def historian_query(
    http: HttpClient,
    headers: dict[str, str],
    *,
    site_id: str | None = None,
    equipment_id: str | None = None,
    limit: int = 50_000,
) -> dict[str, Any]:
    """POST /api/historian/query — pivot rows for SPARQL→DF gates."""
    body: dict[str, Any] = {"limit": min(max(limit, 1), 10_000)}
    if site_id:
        body["site_id"] = site_id
    if equipment_id:
        body["equipment_id"] = equipment_id
    return http.post_json("/api/historian/query", headers=headers, json_body=body)


def mint_opaque_point_iri(building_id: str, equipment_id: str, point_key: str) -> str:
    """Same Soft-OPEN R5 shape the Haystack projector emits into Turtle."""
    return (
        f"urn:openfdd:site/{building_id}/equip/{equipment_id}/point/{point_key}"
    )


def point_resolve(
    http: HttpClient,
    headers: dict[str, str],
    *,
    point_iri: str,
    include_history: bool = True,
    max_points: int = 2000,
) -> dict[str, Any]:
    """GET /api/model/point-resolve — opaque IRI → openfdd_key (+ Timescale samples)."""
    return http.get_json(
        "/api/model/point-resolve",
        headers=headers,
        params={
            "point_iri": point_iri,
            "include_history": "true" if include_history else "false",
            "max_points": max_points,
        },
    )


def fdd_run(
    http: HttpClient,
    headers: dict[str, str],
    *,
    building_id: str,
    rule_ids: list[str] | None = None,
    equipment_id: str | None = None,
    params: dict[str, Any] | None = None,
    force_new_data: bool = True,
) -> dict[str, Any]:
    """POST /api/fdd/run — registry mode only (no raw SQL on product path)."""
    body: dict[str, Any] = {
        "mode": "registry",
        "building_id": building_id,
        "force_new_data": force_new_data,
    }
    if rule_ids:
        body["rule_ids"] = rule_ids
    if equipment_id:
        body["equipment_id"] = equipment_id
    if params:
        body["params"] = params
    return http.post_json("/api/fdd/run", headers=headers, json_body=body)


def fdd_plot(
    http: HttpClient,
    headers: dict[str, str],
    *,
    building_id: str,
    equipment_id: str,
    rule_id: str,
    max_points: int = 1500,
) -> dict[str, Any]:
    """GET /api/fdd/plot — Soft-OPEN plot bool gate (point_count, no screenshots)."""
    return http.get_json(
        "/api/fdd/plot",
        headers=headers,
        params={
            "building_id": building_id,
            "equipment_id": equipment_id,
            "rule_id": rule_id,
            "max_points": max_points,
        },
    )


def fdd_results(
    http: HttpClient,
    headers: dict[str, str],
    *,
    building_id: str,
) -> dict[str, Any]:
    """GET /api/fdd/results — normalized last-run rows."""
    return http.get_json(
        "/api/fdd/results",
        headers=headers,
        params={"building_id": building_id},
    )


def fdd_equipment(
    http: HttpClient,
    headers: dict[str, str],
    *,
    building_id: str,
) -> dict[str, Any]:
    """GET /api/fdd/equipment — Timescale-stamped inventory."""
    return http.get_json(
        "/api/fdd/equipment",
        headers=headers,
        params={"building_id": building_id},
    )


def unique_softopen_building_id(*, shortsha: str | None = None) -> str:
    """Unique Soft-OPEN site id for Railway lesson/stress runs (not a campus name)."""
    import datetime as _dt

    day = _dt.datetime.utcnow().strftime("%Y%m%d")
    sha = (shortsha or os.environ.get("OPENFDD_SOFTOPEN_SHA") or "local").strip()
    sha = sha.removeprefix("sha-")[:7] or "local"
    return f"SOFTOPEN_{day}_{sha}"


def analytics_post(
    http: HttpClient,
    headers: dict[str, str],
    path: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """POST /api/analytics/* — path must start with /api/analytics/."""
    if not path.startswith("/api/analytics/"):
        raise ValueError(f"analytics path must be under /api/analytics/: {path}")
    return http.post_json(path, headers=headers, json_body=body)


def print_table(title: str, rows: list[dict[str, str]], *, limit: int = 20) -> None:
    safe_print(f"\n{title}  ({len(rows)} rows)")
    if not rows:
        safe_print("  (empty)")
        return
    keys = list(rows[0].keys())
    shown = rows[:limit]
    cells = [[short(str(row.get(k, ""))) for k in keys] for row in shown]
    widths = [max(len(k), *(len(r[i]) for r in cells)) for i, k in enumerate(keys)]
    safe_print("  " + "  ".join(k.ljust(widths[i]) for i, k in enumerate(keys)))
    safe_print("  " + "  ".join("-" * w for w in widths))
    for row in cells:
        safe_print("  " + "  ".join(row[i].ljust(widths[i]) for i in range(len(keys))))
    if len(rows) > limit:
        safe_print(f"  ... +{len(rows) - limit} more")


def banner(name: str, *, base_url: str, building_id: str | None = None) -> None:
    safe_print(name)
    safe_print(f"  server       {base_url}")
    if building_id:
        safe_print(f"  building_id  {building_id}")
    safe_print("  vocab        Project Haystack RDF (Turtle) / ofdd: package graph")
    safe_print("  soft-open    Soft-OPEN ≠ FQ")


def require_building_id(args: argparse.Namespace) -> str:
    bid = (getattr(args, "building_id", None) or "").strip()
    if not bid:
        raise SystemExit(
            "building_id required: pass --building-id or set OPENFDD_STRESS_BUILDING_ID "
            "(synthetic site only — no private consumer names)"
        )
    return bid


def ensure_repo_on_path() -> Path:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return REPO


# Child ↔ run_gate.py verdict protocol. Exit 0 is PASS only when the child also
# wrote a PASS result file; 2 is BLOCKED (fixture / precondition missing); any
# other code is FAIL.
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2
RESULT_FILE_ENV = "OPENFDD_STRESS_RESULT_FILE"
RUN_ID_ENV = "OPENFDD_STRESS_RUN_ID"
_CHECKS: list[dict[str, Any]] = []
_OBSERVATIONS: dict[str, Any] = {}
_ACTIVE_CHILD = False


def record_check(name: str, passed: bool, *, comparisons: int = 0) -> None:
    """Record a real finite assertion, never inferred from exit zero alone."""
    if not name or type(passed) is not bool or type(comparisons) is not int or comparisons < 0:
        raise ValueError("invalid assertion or comparison count")
    if not _ACTIVE_CHILD:
        return
    if any(check["id"] == name for check in _CHECKS):
        raise ValueError("duplicate assertion id")
    _CHECKS.append({"id": name, "status": "PASS" if passed else "FAIL",
                    "comparison_count": comparisons})


def status_for_exit(code: int) -> str:
    if code == EXIT_PASS:
        return "PASS"
    if code == EXIT_BLOCKED:
        return "BLOCKED"
    return "FAIL"


def _exit_code(value: Any) -> int:
    if value is None:
        return EXIT_PASS
    if isinstance(value, bool):
        return EXIT_FAIL if value else EXIT_PASS
    if isinstance(value, int):
        return value
    safe_print(str(value), file=sys.stderr)
    return EXIT_FAIL


def write_result(script: str, code: int, *, path: str | None = None) -> None:
    target = path or os.environ.get(RESULT_FILE_ENV)
    if not target:
        return
    out = Path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).parent / script
    body = {"schema_version": 2, "script": script, "exit_code": code,
            "status": status_for_exit(code), "run_id": os.environ.get(RUN_ID_ENV),
            "base_url": os.environ.get("OPENFDD_STRESS_BASE", DEFAULT_BASE),
            "building_id": os.environ.get("OPENFDD_STRESS_BUILDING_ID", ""),
            "expected_version": os.environ.get("OPENFDD_STRESS_EXPECT_VERSION"),
            "observed_version": _OBSERVATIONS.get("observed_version"),
            "assertion_count": len(_CHECKS), "checks": _CHECKS,
            "comparison_count": sum(check["comparison_count"] for check in _CHECKS),
            "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest()
                if script_path.is_file() else None}
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(body, allow_nan=False), encoding="utf-8")
    temp.replace(out)


def run_child(main: Any, script: str) -> int:
    """Run a gate ``main`` and record its verdict for ``run_gate.py``.

    An uncaught exception records FAIL and propagates (non-zero exit).
    """
    code = EXIT_FAIL
    global _ACTIVE_CHILD
    _ACTIVE_CHILD = True
    _CHECKS.clear()
    _OBSERVATIONS.clear()
    try:
        code = _exit_code(main())
    except SystemExit as exc:
        code = _exit_code(exc.code)
    finally:
        if code == EXIT_PASS:
            if any(check["status"] != "PASS" for check in _CHECKS):
                code = EXIT_FAIL
            elif not _CHECKS:
                code = EXIT_BLOCKED
        try:
            write_result(script, code)
        finally:
            _ACTIVE_CHILD = False
    return code
