"""Normal Framework HTTP client (standard library only).

Talks to an NF box on the LAN or through the Normal Online portal over ``/api/v1/*``
(gRPC-JSON). Nothing here knows a site, equipment name, point name, uuid or IP.

Auth:
  * ``None``                                  open box (no login)
  * ``("basic", user, password)``             a front door with HTTP basic auth (console login)
  * ``("portal", client_id, client_secret)``  NF API key: client-credentials token from
                                              ``/api/v1/auth/token``, refreshed on expiry / 401

Retries apply to idempotent calls only (every read, plus the token call) on HTTP 403 / 429 / 5xx and
connection errors, with exponential backoff. NF has a known intermittent empty-body 403 on the token
call that succeeds moments later. The one non-idempotent call, ``start_hook`` (StartHook), is sent
exactly once: if its response is lost, look at the runs instead of firing a second run.
"""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

UA = "open-fdd-nf/1.0"
RETRY_CODES = (403, 429, 500, 502, 503, 504)
BATCH = 40  # uuids per point/data request (keeps the URL short)
CHUNK_DAYS = 7  # NF caps samples per request; history is fetched in pieces of at most 7 days
PAGE_SIZE = 500
PENDING_STATES = ("STATE_RUNNING", "STATE_ENQUEUED", "STATE_SCHEDULED", "STATE_UNSPECIFIED", None)
MAX_PAGES = 10_000


class NFError(RuntimeError):
    """Any failure talking to NF (HTTP error after retries, bad payload, paging loop)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def to_iso_z(ts: datetime | str) -> str:
    """UTC ISO-8601 with a Z suffix (whole seconds), as NF expects for ``from`` / ``to``."""
    if isinstance(ts, str):
        return ts
    return _utc(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


_FRAC = re.compile(r"\.(\d+)")


def parse_nf_ts(ts: str) -> datetime:
    """Parse an NF timestamp (``Z`` suffix, nanosecond fractions allowed) to an aware UTC datetime."""
    s = str(ts).strip().replace("Z", "+00:00")
    s = _FRAC.sub(lambda m: "." + (m.group(1) + "000000")[:6], s, count=1)
    return _utc(datetime.fromisoformat(s))


def sample_value(s: Mapping[str, Any]) -> float | None:
    """Number from one history sample (double / real / boolean / enumerated / unsigned / signed)."""
    v = s.get("double", s.get("real"))
    if v is None and isinstance(s.get("boolean"), bool):
        v = float(s["boolean"])
    if v is None:
        v = s.get("enumerated", s.get("unsigned", s.get("signed")))
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _load_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    file = Path(path).expanduser()
    if not file.is_file():
        raise NFError(f"env file not found: {file}")
    out: dict[str, str] = {}
    for line in file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip("'\"")
    return out


class NFClient:
    """Read-only client for one NF box (see the module docstring for auth and retries)."""

    def __init__(
        self,
        base_url: str,
        auth: tuple | None = None,
        timeout: float = 60.0,
        ca_file: str | os.PathLike[str] | None = None,
        *,
        retries: int = 4,
        backoff: float = 1.0,
        sleep: Callable[[float], None] | None = None,
    ):
        if not base_url:
            raise NFError("NF base URL is empty (pass base_url or set NF_URL)")
        self.base_url = base_url.rstrip("/")
        if auth is not None and (not auth or auth[0] not in ("basic", "portal") or len(auth) != 3):
            raise NFError('auth must be None, ("basic", user, password) or ("portal", client_id, client_secret)')
        self.auth = auth
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.backoff = backoff
        self._sleep = sleep
        self._ctx: ssl.SSLContext | None = None
        if self.base_url.lower().startswith("https"):
            self._ctx = ssl.create_default_context()
            if ca_file:
                self._ctx.load_verify_locations(cafile=str(Path(ca_file).expanduser()))
        self._token: str | None = None
        self._token_exp = 0.0

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_env(
        cls,
        via: str | None = None,
        env_file: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        **kw: Any,
    ) -> "NFClient":
        """Build a client from the environment (and optionally a KEY=VALUE file; real env wins).

        ``via="lan"`` prefers ``NF_LAN_URL``; ``via="portal"`` prefers ``NFURL``; with no ``via``
        the order is ``NF_URL``, ``NFURL``, ``NF_LAN_URL``. Credentials: ``NF_CLIENT_ID`` +
        ``NF_CLIENT_SECRET`` (API key, token flow) else ``NF_CONSOLE_USER`` + ``NF_CONSOLE_PASSWORD``
        (basic). ``NF_CA_FILE`` adds a self-signed LAN certificate.
        """
        merged: dict[str, str] = {}
        path = env_file or os.environ.get("NF_ENV_FILE")
        if path:
            merged.update(_load_env_file(path))
        merged.update(os.environ if env is None else env)
        if via not in (None, "lan", "portal"):
            raise NFError('via must be "lan" or "portal"')
        order = {
            "lan": ("NF_LAN_URL", "NF_URL", "NFURL"),
            "portal": ("NFURL", "NF_URL", "NF_LAN_URL"),
            None: ("NF_URL", "NFURL", "NF_LAN_URL"),
        }[via]
        url = next((merged[k] for k in order if merged.get(k)), "")
        if not url:
            raise NFError("set " + " or ".join(order) + " (environment or --env FILE)")
        auth: tuple | None = None
        if merged.get("NF_CLIENT_ID") and merged.get("NF_CLIENT_SECRET"):
            auth = ("portal", merged["NF_CLIENT_ID"], merged["NF_CLIENT_SECRET"])
        elif merged.get("NF_CONSOLE_USER") and merged.get("NF_CONSOLE_PASSWORD"):
            auth = ("basic", merged["NF_CONSOLE_USER"], merged["NF_CONSOLE_PASSWORD"])
        kw.setdefault("ca_file", merged.get("NF_CA_FILE") or None)
        return cls(url, auth=auth, **kw)

    # ------------------------------------------------------------------ HTTP
    def _auth_header(self) -> dict[str, str]:
        if not self.auth:
            return {}
        if self.auth[0] == "basic":
            raw = f"{self.auth[1]}:{self.auth[2]}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        if self._token is None or time.time() >= self._token_exp:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _fetch_token(self) -> None:
        _, cid, secret = self.auth  # type: ignore[misc]
        body = self._raw("POST", "/api/v1/auth/token", {
            "client_id": cid, "client_secret": secret, "grant_type": "client_credentials",
        }, headers={})
        token = body.get("accessToken") or body.get("access_token")
        if not token:
            raise NFError(f"no accessToken in token response (keys: {sorted(body)})")
        ttl = body.get("expiresIn") or body.get("expires_in")
        try:
            ttl_s = float(ttl) if ttl is not None else 300.0
        except (TypeError, ValueError):
            ttl_s = 300.0
        self._token = str(token)
        self._token_exp = time.time() + max(ttl_s - 30.0, 5.0)  # refresh a little early

    def _raw(self, method: str, path: str, body: Any, headers: Mapping[str, str], once: bool = False) -> dict:
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {"User-Agent": UA, "Accept": "application/json", **headers}
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        last: NFError | None = None
        tries = 1 if once else self.retries
        for attempt in range(1, tries + 1):
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                last = NFError(f"{method} {path.split('?')[0]} failed HTTP {exc.code}: {detail}", exc.code)
                if once or exc.code not in RETRY_CODES:
                    raise last from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = NFError(f"{method} {path.split('?')[0]} failed: {exc}")
            except json.JSONDecodeError as exc:
                raise NFError(f"{method} {path.split('?')[0]}: response is not JSON ({exc})") from exc
            if attempt < tries:
                (self._sleep or time.sleep)(self.backoff * 2 ** (attempt - 1))
        assert last is not None
        raise last

    def request(self, method: str, path: str, body: Any = None, *, once: bool = False) -> dict:
        """One authenticated call (retried unless ``once``: reads are idempotent, StartHook is not).

        A 401 with a portal token triggers one token refresh and a repeat (a 401 means nothing ran).
        """
        try:
            return self._raw(method, path, body, self._auth_header(), once)
        except NFError as exc:
            if exc.status == 401 and self.auth and self.auth[0] == "portal":
                self._token = None
                return self._raw(method, path, body, self._auth_header(), once)
            raise

    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, body: Any) -> dict:
        return self.request("POST", path, body)

    # ------------------------------------------------------------------ hooks
    def start_hook(self, app_id: str, hook_id: str, args: Mapping[str, Any] | None = None) -> str:
        """StartHook: run an on-request hook once now with ``args``; returns the run id (``pid``). Sent once, never retried."""
        path = f"/api/v1/apps/{urllib.parse.quote(app_id, safe='')}/hooks/{urllib.parse.quote(hook_id, safe='')}"
        pid = self.request("POST", path, {"args": dict(args or {})}, once=True).get("pid")
        if not pid:
            raise NFError("StartHook returned no run id (pid)")
        return str(pid)

    def hook_runs(self, app_id: str, hook_id: str, page_size: int = 10) -> list[dict]:
        """Recent runs of a hook, newest first, with their results (events)."""
        path = (f"/api/v1/apps/{urllib.parse.quote(app_id, safe='')}/hooks/{urllib.parse.quote(hook_id, safe='')}"
                f"/runs?page_size={int(page_size)}&include_results=true")
        return list(self.get(path).get("runs") or [])

    def run_hook(self, app_id: str, hook_id: str, args: Mapping[str, Any] | None = None, *,
                 timeout: float = 120.0, poll: float = 1.0) -> dict:
        """Start an on-request hook and wait for its run: returns the finished run (``state`` STATE_SUCCESS ...).

        Polls the hook's runs until the run with the started ``pid`` leaves RUNNING / ENQUEUED / SCHEDULED;
        raises ``NFError`` when it is still running after ``timeout`` seconds.
        """
        pid = self.start_hook(app_id, hook_id, args)
        deadline = time.monotonic() + timeout
        while True:
            run = next((r for r in self.hook_runs(app_id, hook_id) if str(r.get("pid")) == pid), None)
            if run is not None and run.get("state") not in PENDING_STATES:
                return run
            if time.monotonic() >= deadline:
                raise NFError(f"hook {app_id}/{hook_id} run {pid} still running after {timeout:g} s (read its runs later)")
            (self._sleep or time.sleep)(poll)

    # ------------------------------------------------------------------ API
    def platform_info(self) -> dict:
        return self.get("/api/v1/platform/info")

    def sites(self) -> list[dict]:
        return list(self.get("/api/v1/sites").get("sites") or [])

    def query_all(self, layer: str = "default", structured_query: dict | None = None,
                  page_size: int = PAGE_SIZE) -> list[dict]:
        """Every record of ``/api/v1/point/query`` on one layer (all pages).

        A repeated ``nextPageToken`` is an error (a paging loop would otherwise never end).
        """
        body: dict[str, Any] = {"pageSize": page_size, "layer": layer}
        if structured_query:
            body["structuredQuery"] = structured_query
        out: list[dict] = []
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            page = self.post("/api/v1/point/query", body)
            out.extend(page.get("points") or [])
            token = page.get("nextPageToken") or ""
            if not token:
                return out
            if token in seen:
                raise NFError("point/query returned a repeated pageToken; refusing to loop")
            seen.add(token)
            body["pageToken"] = token
        raise NFError("point/query: too many pages")

    def point_data(
        self,
        uuids: Sequence[str],
        start: datetime | str,
        end: datetime | str,
        window_sec: int = 300,
        method: str = "AVERAGE",
    ) -> dict[str, list[tuple[datetime, float]]]:
        """Resampled history: ``{uuid: [(utc datetime, value), ...]}`` sorted by time.

        NF resamples on the box (``window`` seconds, ``method`` AVERAGE|MIN|MAX|SUM|FIRST|LAST|COUNT).
        Requests are batched by at most 40 uuids and cut into pieces of at most 7 days.
        """
        t0 = _utc(start) if isinstance(start, datetime) else parse_nf_ts(start)
        t1 = _utc(end) if isinstance(end, datetime) else parse_nf_ts(end)
        ids = list(dict.fromkeys(uuids))
        out: dict[str, dict[datetime, float]] = {u: {} for u in ids}
        pieces: list[tuple[datetime, datetime]] = []
        t = t0
        while t < t1:
            nxt = min(t + timedelta(days=CHUNK_DAYS), t1)
            pieces.append((t, nxt))
            t = nxt
        for a, b in pieces:
            for i in range(0, len(ids), BATCH):
                batch = ids[i:i + BATCH]
                qs = "&".join("uuids=" + urllib.parse.quote(u) for u in batch)
                path = (f"/api/v1/point/data?{qs}&from={to_iso_z(a)}&to={to_iso_z(b)}"
                        f"&window={int(window_sec)}s&method={method}")
                for series in self.get(path).get("data") or []:
                    slot = out.get(series.get("uuid"))
                    if slot is None:
                        continue
                    for s in series.get("values") or []:
                        v = sample_value(s)
                        if v is not None and s.get("ts"):
                            slot[parse_nf_ts(s["ts"])] = v
        return {u: sorted(m.items()) for u, m in out.items()}
