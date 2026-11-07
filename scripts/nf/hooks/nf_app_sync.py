#!/usr/bin/env python3
"""Sync an NF Applications SDK app between open-fdd (source of truth) and an NF box.

The app is described by a manifest next to the hook source, e.g.
``nf-app/app.json`` or ``lite/app.json``: the application (id, runtime,
auth scopes), a map of NF file path -> repo file, and the hook definitions
(UpdateHook bodies). Talks to the NF *local console* API with HTTP Basic auth
(the remote portal token is read-only and cannot deploy).

    # credentials: CONSOLE_USERNAME / CONSOLE_PASSWORD, NF_CONSOLE_URL
    ENV=~/.secrets/nf_site_console.env
    M=nf-app/app.json
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV status $M
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV push   $M   # create/update app, files, hooks; restart
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV push   $M --skip-hooks   # files only
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV push   $M --hook fdd     # files + only the fdd hook
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV run    $M   # run every hook once now (StartHook)
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV pull   $M   # copy NF files back over the repo files
    python3 scripts/nf/hooks/nf_app_sync.py --env $ENV diff   $M   # show NF vs repo differences

``run`` does not touch the schedule. Never prints passwords or the app's API
client secret (GetApplications returns it; this script drops it).
"""

from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "openfdd-nf-app-sync/1.0"


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


class Console:
    def __init__(self, base: str, user: str, password: str):
        self.base = base.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def call(self, method: str, path: str, body=None, ok_404: bool = False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": self.auth, "User-Agent": UA, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode()
        except urllib.error.HTTPError as e:
            if ok_404 and e.code in (404, 500):
                return None
            raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None
        if text.lstrip().startswith("<"):
            raise SystemExit(f"{method} {path} returned HTML (unknown route on this NF version?)")
        return json.loads(text) if text else {}

    def app(self, app_id: str):
        for a in self.call("GET", "/api/v1/apps").get("applications", []):
            if a.get("id") == app_id:
                a.pop("auth", None)  # contains the generated client secret
                return a
        return None

    def read_file(self, app_id: str, nf_path: str) -> bytes | None:
        r = self.call("GET", f"/api/v1/apps/{app_id}/files{nf_path}", ok_404=True)
        return None if r is None else base64.b64decode(r.get("data", ""))


# Local script/stylesheet references in HTML ("app.js", "style.css"), not URLs or absolute paths.
ASSET_REF = re.compile(r'(?<![\w-])(src|href)="(?![a-z][a-z0-9+.-]*:|/|#)([^"?#]+\.(?:js|mjs|css))"')
STAMP = re.compile(r'(\.(?:js|mjs|css))\?v=[0-9a-f]{10}"')


def deploy_bytes(m: dict, rel: str) -> bytes:
    """File bytes as deployed. HTML gets each local asset reference stamped with the asset's
    content hash (app.js -> app.js?v=<sha256[:10]>): NF serves app files with a 5-minute cache,
    so a changed file needs a new URL or browsers mix old and new files after a deploy."""
    path = m["_dir"] / rel
    data = path.read_bytes()
    if not rel.endswith(".html"):
        return data

    def stamp(mo: re.Match) -> str:
        asset = path.parent / mo.group(2)
        if not asset.is_file():
            return mo.group(0)
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:10]
        return f'{mo.group(1)}="{mo.group(2)}?v={digest}"'

    return ASSET_REF.sub(stamp, data.decode("utf-8")).encode("utf-8")


def strip_stamps(data: bytes) -> bytes:
    """Undo deploy_bytes() stamping so pulled HTML matches the repo form."""
    return STAMP.sub(r'\1"', data.decode("utf-8", errors="replace")).encode("utf-8")


def manifest(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))
    m["_dir"] = path.parent
    return m


def cmd_status(c: Console, m: dict) -> int:
    app_id = m["application"]["id"]
    a = c.app(app_id)
    if not a:
        print(f"app {app_id}: not installed")
        return 1
    print(f"app {app_id}: {a.get('status')} files={[f['path'] for f in a.get('files', [])]}")
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


def cmd_push(c: Console, m: dict, skip_hooks: bool = False, only_hooks: list[str] | None = None) -> int:
    spec = m["application"]
    app_id = spec["id"]
    if spec.get("name") and app_slug(spec["name"]) != app_id:
        raise SystemExit(f"manifest id {app_id!r} != NF's id for name {spec['name']!r} ({app_slug(spec['name'])!r}); "
                         "NF ignores the id on create, so make them match")
    if not c.app(app_id):
        print(f"creating app {app_id}")
        c.call("POST", "/api/v1/apps", spec)
        for _ in range(30):
            a = c.app(app_id)
            if a and a.get("status") == "STATUS_INSTALLED":
                break
            time.sleep(2)
    elif spec.get("auth"):
        c.call("PATCH", f"/api/v1/apps/{app_id}", {"id": app_id, "auth": spec["auth"], "updateMask": ["auth"]})
    for nf_path, rel in m["files"].items():
        data = deploy_bytes(m, rel)
        # WriteFile maps the HTTP body to the bytes field: send a JSON string of base64.
        c.call("POST", f"/api/v1/apps/{app_id}/files{nf_path}", base64.b64encode(data).decode())
        print(f"wrote {nf_path} ({len(data)} bytes)")
    # The version the UI shows (static/version.js): generated from the repo, never committed.
    info = version_info(m["_dir"])
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
    # The runtime caches the hook module; restart so new code is loaded.
    c.call("PATCH", f"/api/v1/apps/{app_id}/restart", {})
    print("restarted app runtimes")
    return 0


def cmd_run(c: Console, m: dict, only_hooks: list[str] | None = None) -> int:
    app_id = m["application"]["id"]
    rc = 0
    for hook in [h for h in m["hooks"] if not only_hooks or h["id"] in only_hooks]:
        r = c.call("POST", f"/api/v1/apps/{app_id}/hooks/{hook['id']}", {})
        pid = r.get("pid")
        print(f"started {hook['id']} pid={pid}")
        for _ in range(30):
            time.sleep(2)
            runs = c.call("GET", f"/api/v1/apps/{app_id}/hooks/{hook['id']}/runs"
                                 "?page_size=5&include_results=true&include_logs=true").get("runs", [])
            run = next((x for x in runs if x.get("pid") == pid), None)
            if run and run.get("state") not in ("STATE_RUNNING", "STATE_ENQUEUED", "STATE_SCHEDULED"):
                print(f"  {run['state']} start={run.get('startTime')}")
                for g in (run.get("results") or {}).values():
                    if g.get("error"):
                        print(f"  error: {g['error'].get('message')}")
                    for e in g.get("events", []):
                        print(f"  event {e.get('ts')}: {e.get('message')}")
                if run["state"] != "STATE_SUCCESS":
                    rc = 1
                break
        else:
            print("  timed out waiting for the run")
            rc = 1
    return rc


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync an NF app manifest with an NF console")
    ap.add_argument("--env", type=Path, default=Path("~/.secrets/nf_site_console.env"))
    ap.add_argument("--console", help="console base URL (default NF_CONSOLE_URL from --env)")
    ap.add_argument("action", choices=["status", "push", "run", "pull", "diff"])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--skip-hooks", action="store_true",
                    help="push: write files only, leave hook definitions alone (e.g. a bench that already runs them)")
    ap.add_argument("--hook", action="append", dest="hooks", metavar="ID",
                    help="push/run: only these hook ids (repeatable), e.g. --hook fdd on a box whose weather comes from elsewhere")
    a = ap.parse_args()
    env = load_env(a.env)
    if not env.get("CONSOLE_USERNAME") or not env.get("CONSOLE_PASSWORD"):
        raise SystemExit(f"CONSOLE_USERNAME / CONSOLE_PASSWORD missing from {a.env}")
    console = a.console or env.get("NF_CONSOLE_URL")
    if not console:
        raise SystemExit(f"NF_CONSOLE_URL missing from {a.env} (or pass --console)")
    c = Console(console, env["CONSOLE_USERNAME"], env["CONSOLE_PASSWORD"])
    m = manifest(a.manifest)
    if a.action == "status":
        return cmd_status(c, m)
    if a.action == "push":
        return cmd_push(c, m, a.skip_hooks, a.hooks)
    if a.action == "run":
        return cmd_run(c, m, a.hooks)
    return cmd_pull(c, m, write=(a.action == "pull"))


if __name__ == "__main__":
    sys.exit(main())
