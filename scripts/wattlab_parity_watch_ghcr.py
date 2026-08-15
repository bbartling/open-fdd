#!/usr/bin/env python3
"""Poll GHCR for a newer openfdd-central image than a baseline created timestamp.

Picks the newest image by OCI config `created` across all tags (nightly/sha-/semver).
Prints AGENT_LOOP_WAKE_ghcr_newer when a newer successful image appears.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path


def _token(repo: str) -> str:
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{repo}:pull"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)["token"]


def _get_json(url: str, tok: str, accept: str) -> tuple[dict, dict]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {tok}", "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        headers = {k.lower(): v for k, v in r.headers.items()}
        return json.loads(r.read()), headers


def newest_central(repo: str = "bbartling/openfdd-central") -> dict:
    tok = _token(repo)
    tags, _ = _get_json(
        f"https://ghcr.io/v2/{repo}/tags/list",
        tok,
        "application/json",
    )
    rows: list[tuple[str, str, str]] = []
    for tag in tags.get("tags") or []:
        try:
            man, hdr = _get_json(
                f"https://ghcr.io/v2/{repo}/manifests/{tag}",
                tok,
                "application/vnd.oci.image.index.v1+json, "
                "application/vnd.docker.distribution.manifest.list.v2+json, "
                "application/vnd.oci.image.manifest.v1+json, "
                "application/vnd.docker.distribution.manifest.v2+json",
            )
            if "config" not in man and "manifests" in man:
                amd = next(
                    (
                        m
                        for m in man["manifests"]
                        if m.get("platform", {}).get("architecture") == "amd64"
                    ),
                    None,
                )
                if not amd:
                    continue
                man, _ = _get_json(
                    f"https://ghcr.io/v2/{repo}/manifests/{amd['digest']}",
                    tok,
                    amd["mediaType"],
                )
                digest = amd["digest"]
            else:
                digest = hdr.get("docker-content-digest") or man.get("config", {}).get(
                    "digest", ""
                )
            cfg_digest = man["config"]["digest"]
            req = urllib.request.Request(
                f"https://ghcr.io/v2/{repo}/blobs/{cfg_digest}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                cfg = json.load(r)
            created = cfg.get("created") or ""
            rows.append((created, tag, digest))
        except Exception:
            continue
    if not rows:
        raise RuntimeError("no readable GHCR tags")
    rows.sort(reverse=True)
    created, tag, digest = rows[0]
    return {"created": created, "tag": tag, "digest": digest, "top": rows[:5]}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default="bbartling/openfdd-central")
    p.add_argument(
        "--baseline-created",
        required=True,
        help="ISO created timestamp already tested; wake only if newer",
    )
    p.add_argument("--interval-sec", type=int, default=300)
    p.add_argument("--state", type=Path, default=Path("/tmp/wattlab_parity_ghcr_watch.json"))
    args = p.parse_args()

    baseline = args.baseline_created
    print(
        f"watching GHCR {args.repo} for created > {baseline} every {args.interval_sec}s",
        flush=True,
    )
    while True:
        try:
            info = newest_central(args.repo)
            args.state.write_text(json.dumps(info, indent=2), encoding="utf-8")
            if info["created"] > baseline:
                payload = {
                    "prompt": (
                        f"Newest GHCR {args.repo} is newer than baseline. "
                        f"Pull tag={info['tag']} created={info['created']} "
                        f"digest={info['digest']}, stack up react-ot, re-run "
                        "vibe19 oracle + OFDD Rust capture + wattlab_parity_diff, "
                        "update BUGREPORT. Then update watch baseline to this created."
                    ),
                    "tag": info["tag"],
                    "created": info["created"],
                    "digest": info["digest"],
                }
                print(
                    f"AGENT_LOOP_WAKE_ghcr_newer {json.dumps(payload)}",
                    flush=True,
                )
                return 0
            print(
                f"still waiting: newest={info['tag']} created={info['created']}",
                flush=True,
            )
        except Exception as e:
            print(f"watch error: {e}", flush=True)
        time.sleep(max(30, args.interval_sec))


if __name__ == "__main__":
    raise SystemExit(main())
