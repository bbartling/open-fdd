#!/usr/bin/env python3
"""Pick the newest GHCR image by OCI config `created`, not tag name.

`:nightly`, `:latest`, and `sha-*` sort order are not "newest". Agents that
pull by tag name demo the wrong bits. This script is the source of truth.

  ./scripts/ghcr_newest_by_created.py openfdd-central
  ./scripts/ghcr_newest_by_created.py --json openfdd-central openfdd-web
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

GHCR = "ghcr.io"
OWNER = "bbartling"


def _token(repo: str) -> str:
    url = f"https://{GHCR}/token?service={GHCR}&scope=repository:{repo}:pull"
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


def newest_for(package: str, owner: str = OWNER) -> dict:
    name = package.removeprefix(f"{owner}/")
    repo = f"{owner}/{name}"
    tok = _token(repo)
    tags, _ = _get_json(
        f"https://{GHCR}/v2/{repo}/tags/list",
        tok,
        "application/json",
    )
    rows: list[dict] = []
    for tag in tags.get("tags") or []:
        try:
            man, hdr = _get_json(
                f"https://{GHCR}/v2/{repo}/manifests/{tag}",
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
                    f"https://{GHCR}/v2/{repo}/manifests/{amd['digest']}",
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
                f"https://{GHCR}/v2/{repo}/blobs/{cfg_digest}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                cfg = json.load(r)
            created = cfg.get("created") or ""
            revision = ""
            labels = cfg.get("config", {}).get("Labels") or {}
            revision = str(labels.get("org.opencontainers.image.revision") or "")
            rows.append(
                {
                    "created": created,
                    "tag": tag,
                    "digest": digest,
                    "revision": revision,
                    "image": f"{GHCR}/{repo}:{tag}",
                }
            )
        except Exception:
            continue
    if not rows:
        raise RuntimeError(f"no readable GHCR tags for {repo}")
    rows.sort(key=lambda r: r["created"], reverse=True)
    top = rows[0]
    return {
        "package": name,
        "created": top["created"],
        "tag": top["tag"],
        "digest": top["digest"],
        "revision": top["revision"],
        "image": top["image"],
        "top": rows[:8],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "packages",
        nargs="*",
        default=["openfdd-central"],
        help="GHCR package names (default: openfdd-central)",
    )
    p.add_argument("--json", action="store_true", help="machine-readable")
    args = p.parse_args()
    out = []
    for pkg in args.packages:
        info = newest_for(pkg)
        out.append(info)
        if not args.json:
            print(
                f"{info['package']}\t{info['tag']}\t{info['created']}\t{info['image']}"
            )
    if args.json:
        print(json.dumps(out if len(out) > 1 else out[0], indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
