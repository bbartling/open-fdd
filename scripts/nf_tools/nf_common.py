"""Shared NF REST helpers for the nf_* tools (auth, paging, tag filters).

Auth follows nf_portal_sensors.py: POST {base}/api/v1/auth/token with
client_credentials, then Bearer on /api/v1/point/query and /api/v1/point/data.
Settings come from the environment or an env file (--env-file / NF_ENV_FILE):

  NFURL=https://<installation>.normal-online.net   (or NF_LAN_URL for --via lan)
  NF_CLIENT_ID=...
  NF_CLIENT_SECRET=...

Secrets are never printed or logged. Nothing here knows a site, equip or point
name; everything is selected by tags passed in by the caller.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

UA = "nf-tools/1.0"
RETRY_CODES = (403, 429, 502, 503, 504)
RETRIES = 4
PATHS = {"portal": "NFURL", "lan": "NF_LAN_URL"}
GENERIC_MARKERS = {"point", "his", "cur", "writable"}


# ---------------------------------------------------------------- settings
def load_env_file(path: str | os.PathLike | None) -> None:
    """KEY=VALUE lines into os.environ (existing env wins). Values never echoed."""
    if not path:
        return
    p = Path(os.path.expanduser(str(path)))
    if not p.is_file():
        raise SystemExit(f"env file not found: {p}")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def settings(env_file: str | None, via: str = "portal") -> tuple[str, str, str]:
    load_env_file(env_file or os.environ.get("NF_ENV_FILE"))
    var = PATHS[via]
    base = os.environ.get(var, "").rstrip("/")
    cid = os.environ.get("NF_CLIENT_ID", "")
    sec = os.environ.get("NF_CLIENT_SECRET", "")
    missing = [n for n, v in ((var, base), ("NF_CLIENT_ID", cid), ("NF_CLIENT_SECRET", sec)) if not v]
    if missing:
        raise SystemExit(f"missing settings: {', '.join(missing)} (env or --env-file)")
    return base, cid, sec


# ---------------------------------------------------------------- http
def _request(url: str, body: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    short = url.split("?")[0]
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_CODES and attempt < RETRIES:
                time.sleep(2 ** attempt)
                continue
            detail = exc.read().decode(errors="replace")[:300]
            raise SystemExit(f"{short} failed HTTP {exc.code}: {detail}") from exc
    raise AssertionError("unreachable")


def bearer_token(base: str, cid: str, secret: str) -> str:
    body = _request(f"{base}/api/v1/auth/token", {
        "client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    tok = body.get("accessToken") or body.get("access_token")
    if not tok:
        raise SystemExit(f"no accessToken in auth response (keys {sorted(body)})")
    return tok


class NF:
    """Read-only client unless a caller explicitly uses post()."""

    def __init__(self, env_file: str | None = None, via: str = "portal"):
        self.base, cid, sec = settings(env_file, via)
        self.token = bearer_token(self.base, cid, sec)

    def query(self, layer: str, *clauses: dict, page_size: int = 500) -> list[dict]:
        body: dict = {"pageSize": page_size, "layer": layer}
        if clauses:
            body["structuredQuery"] = clauses[0] if len(clauses) == 1 else {"and": list(clauses)}
        out: list[dict] = []
        while True:
            page = _request(f"{self.base}/api/v1/point/query", body, self.token)
            out.extend(page.get("points") or [])
            body["pageToken"] = page.get("nextPageToken") or ""
            if not body["pageToken"]:
                return out

    def history(self, uuid: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        from datetime import timedelta
        out: list[tuple[datetime, float]] = []
        chunk = start
        while chunk < end:
            ce = min(chunk + timedelta(days=1), end)
            q = urlencode({"from": iso(chunk), "to": iso(ce), "uuids": uuid})
            body = _request(f"{self.base}/api/v1/point/data?{q}", None, self.token)
            for series in body.get("data") or []:
                for s in series.get("values") or []:
                    v = s.get("double", s.get("real"))
                    if v is None or not s.get("ts"):
                        continue
                    out.append((parse_ts(s["ts"]), float(v)))
            chunk = ce
        out.sort()
        return out


def field(prop: str, text: str) -> dict:
    return {"field": {"property": prop, "text": text}}


# ---------------------------------------------------------------- time
def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(raw: str) -> datetime:
    head, _, frac = raw.rstrip("Z").partition(".")
    frac = (frac + "000000")[:6]
    return datetime.fromisoformat(f"{head}.{frac}+00:00")


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """ISO timestamp, or relative like 24h / 3d / 30m (ago), or 'now'."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    t = text.strip()
    if t == "now":
        return now
    if t[:-1].replace(".", "", 1).isdigit() and t[-1] in "mhd":
        n = float(t[:-1])
        unit = {"m": "minutes", "h": "hours", "d": "days"}[t[-1]]
        return now - timedelta(**{unit: n})
    dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.astimezone()  # naive = box-local


# ---------------------------------------------------------------- tags/filters (pure)
def split_list(text: str | None) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def attrs(rec: dict) -> dict:
    return rec.get("attrs") or {}


def markers(rec: dict) -> list[str]:
    return split_list(attrs(rec).get("markers"))


def rec_kind(rec: dict) -> str:
    """site / equip / point / device / other, from markers or pointType."""
    m = set(markers(rec))
    pt = (rec.get("pointType") or "").upper()
    if "site" in m or pt == "SITE":
        return "site"
    if "equip" in m or pt == "EQUIPMENT":
        return "equip"
    if "device" in m or pt == "DEVICE":
        return "device"
    if "point" in m:
        return "point"
    return "other"


def site_matches(rec: dict, site: str | None) -> bool:
    if not site:
        return True
    a = attrs(rec)
    return site in (a.get("siteRef"), a.get("id") if rec_kind(rec) == "site" else None)


def point_matches(rec: dict, *, site: str | None = None, equip: str | None = None,
                  tags: list[str] = (), exclude: list[str] = (), point_class: str | None = None,
                  equip_ids: set[str] | None = None) -> bool:
    """AND of all given criteria. equip_ids restricts equipRef to a set (from --equip-tag)."""
    a = attrs(rec)
    m = set(markers(rec))
    if not site_matches(rec, site):
        return False
    if equip and a.get("equipRef") != equip:
        return False
    if equip_ids is not None and a.get("equipRef") not in equip_ids:
        return False
    if not set(tags) <= m:
        return False
    if set(exclude) & m:
        return False
    if point_class and a.get("class") != point_class:
        return False
    return True


def equip_ids_with_tags(records: list[dict], tags: list[str], site: str | None = None) -> set[str]:
    """ids of equip records carrying every marker in tags (optionally on a site)."""
    out = set()
    for r in records:
        if rec_kind(r) == "equip" and set(tags) <= set(markers(r)) and site_matches(r, site):
            out.add(attrs(r).get("id") or r.get("name"))
    return out


def latest(rec: dict) -> tuple[str | None, float | None]:
    lv = rec.get("latestValue") or {}
    v = lv.get("double", lv.get("real"))
    return lv.get("ts"), v


def flat_row(rec: dict) -> dict:
    a = attrs(rec)
    ts, v = latest(rec)
    return {
        "uuid": rec.get("uuid"), "kind": rec_kind(rec), "name": rec.get("name"),
        "dis": a.get("dis"), "id": a.get("id"), "siteRef": a.get("siteRef"),
        "equipRef": a.get("equipRef"), "deviceRef": a.get("deviceRef"),
        "class": a.get("class"), "markers": ",".join(markers(rec)), "unit": a.get("unit") or rec.get("displayUnits"),
        "period": a.get("period") or rec.get("period"), "latest_ts": ts, "latest_value": v,
    }


def write_rows(rows: list[dict], fmt: str, out=None) -> None:
    import csv
    out = out or sys.stdout
    if fmt == "json":
        json.dump(rows, out, indent=1, ensure_ascii=False, default=str)
        out.write("\n")
        return
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    w = csv.DictWriter(out, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
