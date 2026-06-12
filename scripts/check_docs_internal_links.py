#!/usr/bin/env python3
"""Verify internal links in built Jekyll HTML under _site (GitHub Pages /open-fdd/)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE = REPO_ROOT / "_site"
BASEURL = "/open-fdd"

# href patterns we intentionally skip (external, API examples, repo source on GitHub).
SKIP_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
    "tel:",
    "#",
    "javascript:",
)
SKIP_HOSTS = ("localhost", "127.0.0.1", "192.168.", "10.", "172.16.", "172.17.", "172.18.")
HREF_RE = re.compile(r"""href=["']([^"'#]+)(#[^"']*)?["']""", re.IGNORECASE)


def _skip_href(href: str) -> bool:
    raw = href.strip()
    if not raw or raw.startswith(SKIP_PREFIXES):
        return True
    if raw.endswith(".md") and "github.com" not in raw:
        return False  # internal .md in site is always wrong
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        host = (parsed.hostname or "").lower()
        if any(host.startswith(h) or h in host for h in SKIP_HOSTS):
            return True
        if "github.com" in host and "/blob/" in raw:
            return True
        return True
    return False


def _missing_baseurl(href: str) -> bool:
    """Root-absolute paths must include GitHub Pages project baseurl."""
    if not href.startswith("/"):
        return False
    if href.startswith(BASEURL + "/") or href == BASEURL + "/" or href == BASEURL:
        return False
    # Allow root-only anchors and asset paths that Jekyll may emit at repo root (rare).
    if href.startswith("/assets/"):
        return True
    return True


def _site_path_for_href(href: str, site_dir: Path) -> Path | None:
    """Map published href to expected file under _site."""
    path = unquote(urlparse(href).path)
    if BASEURL and path.startswith(BASEURL):
        path = path[len(BASEURL) :] or "/"
    if not path.startswith("/"):
        return None
    rel = path.lstrip("/")
    if not rel:
        candidates = [site_dir / "index.html"]
    else:
        candidates = [
            site_dir / rel,
            site_dir / rel / "index.html",
            site_dir / f"{rel}.html",
        ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def check_site(site_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    skipped: list[str] = []
    if not site_dir.is_dir():
        errors.append(f"Site directory missing: {site_dir} (run Jekyll build first)")
        return errors, skipped

    for html in sorted(site_dir.rglob("*.html")):
        text = html.read_text(encoding="utf-8", errors="replace")
        page_url = "/" + html.relative_to(site_dir).as_posix()
        for match in HREF_RE.finditer(text):
            href = match.group(1)
            if _skip_href(href):
                if href.endswith(".md") and not href.startswith(SKIP_PREFIXES):
                    errors.append(f"{page_url}: links to raw .md (use docs page or GitHub blob): {href}")
                continue
            if href.endswith(".md"):
                errors.append(f"{page_url}: internal .md href (not published): {href}")
                continue
            resolved = _site_path_for_href(href, site_dir)
            if resolved is None:
                if _missing_baseurl(href):
                    errors.append(
                        f"{page_url}: href missing {BASEURL} prefix (use relative_url) → {href}"
                    )
                elif href.startswith(BASEURL) or href.startswith("/"):
                    errors.append(f"{page_url}: broken internal link → {href}")
            elif "github.com" in href:
                skipped.append(href)
    return errors, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site",
        type=Path,
        default=DEFAULT_SITE,
        help="Jekyll output directory (default: _site)",
    )
    args = parser.parse_args()
    errors, _skipped = check_site(args.site.resolve())
    if errors:
        print(f"Docs internal link check FAILED ({len(errors)} issue(s)):", file=sys.stderr)
        for e in errors[:80]:
            print(f"  {e}", file=sys.stderr)
        if len(errors) > 80:
            print(f"  ... and {len(errors) - 80} more", file=sys.stderr)
        return 1
    print("Docs internal link check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
