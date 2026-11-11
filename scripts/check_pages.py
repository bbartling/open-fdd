#!/usr/bin/env python3
"""Check links and the human navigation in a built Jekyll site.

Run after `bundle exec jekyll build`: python3 scripts/check_pages.py docs/_site
"""
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

BASEURL = "/open-fdd"
SITE_URL = "https://bbartling.github.io"
NAV_PAGES = {
    "index.html", "install.html", "modeling.html", "units.html", "sql-rules.html", "pandas-rules.html",
    "fdd-rules.html", "rules/sql-cookbook.html", "rules/pandas-cookbook.html", "rules/parity.html",
    "fdd-data-access.html", "charts.html", "export.html", "rdf-sparql.html", "security.html",
    "python-tools.html", "development.html", "changelog.html", "architecture.html",
}
FORBIDDEN_NAV = ("prompts/", "operations/nf/", "migration/nf-plugin/", "architecture/adr-014")
REDIRECTS = {
    "lite.html": "install.html#choose-full-or-lite",
    "operations/nf/index.html": "install.html",
    "operations/nf/lite-vs-full.html": "install.html#choose-full-or-lite",
    "operations/nf/haystack-tagging.html": "modeling.html",
    "operations/nf/front-door-caddy.html": "install.html#reach-nf-safely",
    "operations/nf/nf-upgrade-compose.html": "install.html#upgrade-pin-and-remove",
    "operations/nf/bacnet-validate.html": "install.html#model-and-verify",
    "operations/nf/migrate-5.0.10.html": "install.html#upgrade-pin-and-remove",
    "operations/nf/migrate-5.0.11.html": "install.html#timescale-option-and-schema-preflight",
    "operations/nf/nf-gotchas.html": "install.html",
    "operations/nf/PORT_NOTES.html": "install.html#reach-nf-safely",
    "migration/nf-plugin/PLAN.html": "architecture.html",
    "migration/nf-plugin/STATUS.html": "architecture.html",
    "migration/nf-plugin/NF_FEATURES.html": "architecture.html",
    "migration/nf-plugin/ARCHIVE_MAP.html": "architecture.html",
    "architecture/adr-014-open-fdd-as-nf-plugin.html": "architecture.html",
}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.nav_links: set[str] = set()
        self.nav_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "nav":
            self.nav_depth += 1
        for key in ("id", "name"):
            if values.get(key):
                self.ids.add(values[key])
        for key in ("href", "src"):
            value = values.get(key)
            if value:
                self.links.append(value)
                if self.nav_depth:
                    self.nav_links.add(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav":
            self.nav_depth = max(0, self.nav_depth - 1)


def read_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser


def local_target(site: Path, source: Path, raw: str) -> tuple[Path | None, str]:
    url = urlparse(raw)
    if url.scheme or url.netloc:
        if url.netloc and url.hostname not in {urlparse(SITE_URL).hostname}:
            return None, ""
        path = unquote(url.path)
    else:
        path = unquote(url.path)
    if not path:
        target = source
    elif path.startswith(BASEURL + "/") or path == BASEURL:
        path = path[len(BASEURL):]
        target = site / path.lstrip("/")
    elif path.startswith("/"):
        target = site / path.lstrip("/")
    else:
        target = (source.parent / path).resolve()
    target = target.resolve()
    try:
        target.relative_to(site)
    except ValueError:
        return site / "__outside_site__", unquote(url.fragment)
    if target.is_dir() or not target.suffix:
        target = target / "index.html"
    return target, unquote(url.fragment)


def main() -> int:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/_site").resolve()
    if not (site / "index.html").is_file():
        print(f"missing built site: {site}", file=sys.stderr)
        return 2
    pages = sorted(site.rglob("*.html"))
    errors: list[str] = []
    parsed = {p: read_page(p) for p in pages}
    checked = 0
    for source, doc in parsed.items():
        for raw in doc.links:
            target, fragment = local_target(site, source, raw)
            if target is None:
                continue
            checked += 1
            if not target.is_file():
                errors.append(f"{source.relative_to(site)}: missing target {raw}")
            elif fragment and target.suffix == ".html":
                target_doc = parsed.get(target)
                if target_doc is None:
                    target_doc = read_page(target)
                if fragment not in target_doc.ids:
                    errors.append(f"{source.relative_to(site)}: missing fragment {raw}")

    nav_links = set().union(*(doc.nav_links for doc in parsed.values()))
    nav_paths = set()
    for href in nav_links:
        target, _ = local_target(site, site / "index.html", href)
        if target:
            try:
                nav_paths.add(target.relative_to(site).as_posix())
            except ValueError:
                pass
    for page in sorted(NAV_PAGES - nav_paths):
        errors.append(f"navigation is missing {page}")
    for href in nav_links:
        if any(part in urlparse(href).path for part in FORBIDDEN_NAV):
            errors.append(f"unpublished page appears in navigation: {href}")

    if (site / "prompts").exists():
        errors.append("docs/prompts was rendered into the Pages site")
    for old, new in REDIRECTS.items():
        target = site / old
        url = BASEURL + "/" + new
        if not target.is_file():
            errors.append(f"missing legacy URL redirect: {old}")
            continue
        content = target.read_text(encoding="utf-8", errors="replace")
        if "Page moved" not in content or url not in content:
            errors.append(f"legacy URL does not redirect to {url}: {old}")

    print(f"checked {checked} built-site links across {len(pages)} HTML pages")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"navigation contains all {len(NAV_PAGES)} target pages; unpublished prompt tree is absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
