#!/usr/bin/env python3
"""Check the docs site: structure and size guardrails (source) and links and navigation (built site).

    python3 scripts/check_pages.py                    # source checks only (no Jekyll needed)
    python3 scripts/check_pages.py docs/_site         # source checks + built-site checks
    python3 scripts/check_pages.py --write-redirects  # (re)write the "Page moved" stubs from REDIRECTS

Source checks (docs/*.md and docs/_config.yml), from issue #1599:
  - the nav is exactly the five sections; children hang off a section via `parent` (no deeper, no hidden extras);
  - every published page is within its prose word budget (tables, code and link targets do not count) and the site total is capped;
  - internal folders (prompts, plans, migration, operations, ...) are excluded from the build;
  - every rule entry in both cookbooks has Inputs, Parameters and Outputs tables with units; both have the units convention block;
  - every "Page moved" stub for a removed URL exists and points at a live target.
Built-site checks: every local link and fragment resolves, the sidebar lists the published pages with the five sections on top,
and no internal folder or Markdown file was rendered.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BASEURL = "/open-fdd"
SITE_URL = "https://bbartling.github.io"
GH = "https://github.com/bbartling/open-fdd"

SECTIONS = ["Rules", "Data model", "Lite vs Full", "Normal Framework", "Legacy"]
HIDDEN_OK = {"index.md", "404.md"}  # the only pages allowed to stay out of the nav
INTERNAL_DIRS = ("prompts", "plans", "scratch", "internal", "private", "migration", "operations", "architecture")
FORBIDDEN_NAV = tuple(d + "/" for d in INTERNAL_DIRS)

DEFAULT_BUDGET = 800  # prose words per published page (tables, code, link targets excluded)
BUDGETS = {
    # generated reference: one structured entry per rule; the prose is the per-rule description and the intro
    "rules/sql-cookbook.md": 3500,
    "rules/pandas-cookbook.md": 2500,
}
TOTAL_BUDGET = 12000  # prose words across every published page

COOKBOOKS = ("rules/sql-cookbook.md", "rules/pandas-cookbook.md")

# Removed or moved URLs keep a stub so old links resolve. Target is a site path (with optional #fragment) or an absolute URL.
REDIRECTS = {
    "lite.html": "editions.html",
    "install.html": "normal-framework.html#install",
    "security.html": "normal-framework.html#security",
    "architecture.html": "legacy.html",
    "units.html": "modeling.html#units-are-si-first",
    "rdf-sparql.html": "modeling.html#rdf-and-sparql",
    "export.html": "charts.html#export",
    "pandas-rules.html": "rules/parity.html#change-a-rule",
    "fdd-rules.html": "rules/",
    "python-tools.html": f"{GH}/blob/master/docs/python-tools.md",
    "development.html": f"{GH}/blob/master/docs/development.md",
    "plot-spec.html": f"{GH}/blob/master/docs/plot-spec.md",
    "changelog.html": f"{GH}/releases",
    "operations/nf/index.html": "normal-framework.html",
    "operations/nf/lite-vs-full.html": "editions.html",
    "operations/nf/haystack-tagging.html": "modeling.html",
    "operations/nf/front-door-caddy.html": "normal-framework.html#security",
    "operations/nf/nf-upgrade-compose.html": "normal-framework.html#upgrade-pin-and-remove",
    "operations/nf/bacnet-validate.html": "normal-framework.html#verify",
    "operations/nf/migrate-5.0.10.html": "normal-framework.html#upgrade-pin-and-remove",
    "operations/nf/migrate-5.0.11.html": "normal-framework.html#install",
    "operations/nf/nf-gotchas.html": "normal-framework.html",
    "operations/nf/PORT_NOTES.html": "normal-framework.html#security",
    "migration/nf-plugin/PLAN.html": "legacy.html",
    "migration/nf-plugin/STATUS.html": "legacy.html",
    "migration/nf-plugin/NF_FEATURES.html": "legacy.html",
    "migration/nf-plugin/ARCHIVE_MAP.html": "legacy.html",
    "architecture/adr-014-open-fdd-as-nf-plugin.html": "legacy.html",
}

STUB = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={url}">'
        '<link rel="canonical" href="{url}"><title>Page moved</title></head><body><p>This page moved to '
        '<a href="{url}">the current documentation</a>.</p></body></html>\n')


def redirect_url(target: str) -> str:
    return target if target.startswith("http") else f"{BASEURL}/{target}"


# --------------------------------------------------------------------------------------------------------------------
# source: front matter, excludes, words
# --------------------------------------------------------------------------------------------------------------------


def front_matter(text: str) -> tuple[dict, str]:
    """(flat key/value dict, body) for a page; a tiny YAML subset is enough for Just the Docs front matter."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*?)\s*$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip("\"'")
    return meta, text[end + 4:]


def excludes() -> list[str]:
    out, on = [], False
    for line in (DOCS / "_config.yml").read_text(encoding="utf-8").splitlines():
        if re.match(r"^exclude:\s*$", line):
            on = True
        elif on and line.startswith("  - "):
            out.append(line[4:].strip())
        elif on and line.strip() and not line.startswith(" "):
            on = False
    return out


def is_excluded(rel: str, patterns: list[str]) -> bool:
    """Jekyll-style exclude: an exact path, or an fnmatch glob (`*` also crosses `/`, as in Jekyll)."""
    return any(rel == pat or fnmatch.fnmatchcase(rel, pat) for pat in patterns)


def prose_words(body: str) -> int:
    body = re.sub(r"```.*?```|~~~.*?~~~", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"\{%.*?%\}", " ", body, flags=re.S)
    text = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("|"))
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def published_pages() -> dict[str, dict]:
    pats = excludes()
    pages = {}
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS).as_posix()
        if rel.startswith(("vendor/", "_site/")) or is_excluded(rel, pats):
            continue
        meta, body = front_matter(path.read_text(encoding="utf-8"))
        pages[rel] = {"meta": meta, "words": prose_words(body), "body": body}
    return pages


def page_url(rel: str, meta: dict) -> str:
    """Built path of a page, relative to the site root."""
    perm = meta.get("permalink")
    if perm:
        perm = perm.lstrip("/")
        return "index.html" if not perm else (perm + "index.html" if perm.endswith("/") else perm)
    return rel[:-3] + ".html"


# --------------------------------------------------------------------------------------------------------------------
# source checks
# --------------------------------------------------------------------------------------------------------------------


def check_navigation(pages: dict[str, dict], errors: list[str]) -> None:
    tops, titles = [], {}
    for rel, p in pages.items():
        m = p["meta"]
        titles[m.get("title", "")] = rel
        hidden = m.get("nav_exclude", "").lower() == "true"
        if hidden and rel not in HIDDEN_OK:
            errors.append(f"{rel}: nav_exclude is not allowed (publish it in a section, or exclude it in _config.yml)")
        if m.get("grand_parent"):
            errors.append(f"{rel}: grand_parent is not allowed; the nav is section > page only")
        if not m.get("title"):
            errors.append(f"{rel}: missing title")
        if not hidden and not m.get("parent"):
            tops.append((float(m.get("nav_order", "999")), m.get("title", "")))
    got = [t for _, t in sorted(tops)]
    if got != SECTIONS:
        errors.append(f"top-level navigation is {got}, expected exactly {SECTIONS}")
    for rel, p in pages.items():
        parent = p["meta"].get("parent")
        if parent and parent not in SECTIONS:
            errors.append(f"{rel}: parent {parent!r} is not one of the five sections")
        title = p["meta"].get("title", "")
        h1 = re.search(r"^# (.+)$", p["body"], flags=re.M)
        if h1 and rel not in HIDDEN_OK and h1.group(1).strip() != title:
            errors.append(f"{rel}: title {title!r} does not match its H1 {h1.group(1).strip()!r}")
    for section in SECTIONS:
        rel = titles.get(section)
        has = bool(rel) and pages[rel]["meta"].get("has_children", "") == "true"
        if any(p["meta"].get("parent") == section for p in pages.values()) and not has:
            errors.append(f"{rel}: section {section!r} has children but not has_children: true")


def check_budgets(pages: dict[str, dict], errors: list[str]) -> int:
    total = 0
    for rel, p in pages.items():
        budget = BUDGETS.get(rel, DEFAULT_BUDGET)
        total += p["words"]
        if p["words"] > budget:
            errors.append(f"{rel}: {p['words']} prose words exceeds its budget of {budget} (cut text, or link instead of repeating)")
    if total > TOTAL_BUDGET:
        errors.append(f"published prose is {total} words, over the site budget of {TOTAL_BUDGET}")
    return total


def check_internal(errors: list[str]) -> None:
    pats = excludes()
    for d in INTERNAL_DIRS:
        base = DOCS / d
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            rel = path.relative_to(DOCS).as_posix()
            if not is_excluded(rel, pats):
                errors.append(f"{rel}: internal material is not excluded in docs/_config.yml")
    if "prompts/**" not in pats:
        errors.append("docs/_config.yml must exclude prompts/**")


def entries(body: str):
    """(rule id, entry text) for each `### RULE` entry of a cookbook."""
    parts = re.split(r"^### (\S+)", body, flags=re.M)
    for i in range(1, len(parts), 2):
        yield parts[i], parts[i + 1]


def table_after(entry: str, label: str) -> str | None:
    m = re.search(r"\*\*" + re.escape(label) + r"\*\*[^\n]*\n\n((?:\|[^\n]*\n?)+|_None\._)", entry)
    return m.group(1) if m else None


def check_cookbooks(pages: dict[str, dict], errors: list[str]) -> None:
    catalog = json.loads((ROOT / "nf-app" / "static" / "fdd-catalog.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in catalog["rules"]}
    for rel in COOKBOOKS:
        page = pages.get(rel)
        if page is None:
            errors.append(f"{rel}: missing from the published site")
            continue
        body = page["body"]
        if "## Units convention" not in body or "| SI unit" not in body:
            errors.append(f"{rel}: missing the units convention block")
        seen = set()
        for rid, entry in entries(body):
            seen.add(rid)
            if "**SQL only.**" in entry:
                continue
            inputs = table_after(entry, "Inputs")
            head = inputs.splitlines()[0] if inputs else ""
            if "SI unit" not in head or "Expected range" not in head:
                errors.append(f"{rel}: {rid} is missing its Inputs units table")
            params = table_after(entry, "Parameters")
            if not params or (params != "_None._" and "SI unit" not in params.splitlines()[0]):
                errors.append(f"{rel}: {rid} is missing its Parameters units table")
            outputs = re.search(r"\*\*Outputs\*\*[^\n]*\n\n(\|[^\n]*)", entry)
            if not outputs or "Unit" not in outputs.group(1):
                errors.append(f"{rel}: {rid} is missing its Outputs units table")
            if "**Parity**" not in entry:
                errors.append(f"{rel}: {rid} is missing its parity status")
        if seen != ids:
            errors.append(f"{rel}: entries differ from fdd-catalog.json (missing {sorted(ids - seen)[:5]}, extra {sorted(seen - ids)[:5]})")


def check_redirect_sources(errors: list[str]) -> None:
    for old, target in REDIRECTS.items():
        path = DOCS / old
        if not path.is_file():
            errors.append(f"missing legacy URL stub docs/{old} (run scripts/check_pages.py --write-redirects)")
        elif STUB.format(url=redirect_url(target)) != path.read_text(encoding="utf-8").replace("\r\n", "\n"):
            errors.append(f"docs/{old} does not redirect to {redirect_url(target)} (run scripts/check_pages.py --write-redirects)")
        if not target.startswith("http"):
            page = target.split("#")[0]
            if page != "rules/" and not (DOCS / page).is_file() and not (DOCS / (page[:-5] + ".md")).is_file():
                errors.append(f"redirect {old} -> {target}: target page does not exist")


def write_redirects() -> None:
    for old, target in REDIRECTS.items():
        path = DOCS / old
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(STUB.format(url=redirect_url(target)), encoding="utf-8", newline="\n")
    print(f"wrote {len(REDIRECTS)} redirect stubs")


def source_checks() -> tuple[list[str], dict[str, dict], int]:
    errors: list[str] = []
    pages = published_pages()
    check_navigation(pages, errors)
    total = check_budgets(pages, errors)
    check_internal(errors)
    check_cookbooks(pages, errors)
    check_redirect_sources(errors)
    return errors, pages, total


# --------------------------------------------------------------------------------------------------------------------
# built site
# --------------------------------------------------------------------------------------------------------------------


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.nav_links: set[str] = set()
        self.top_nav: list[str] = []  # text of first-level sidebar links
        self.nav_depth = 0
        self.ul_depth = 0
        self._cap: list | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "nav":
            self.nav_depth += 1
        if tag == "ul" and self.nav_depth:
            self.ul_depth += 1
        for key in ("id", "name"):
            if values.get(key):
                self.ids.add(values[key])
        for key in ("href", "src"):
            value = values.get(key)
            if value:
                self.links.append(value)
                if self.nav_depth:
                    self.nav_links.add(value)
        if tag == "a" and self.nav_depth and self.ul_depth == 1 and "nav-list-link" in (values.get("class") or ""):
            self._cap = []

    def handle_data(self, data: str) -> None:
        if self._cap is not None:
            self._cap.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._cap is not None:
            self.top_nav.append("".join(self._cap).strip())
            self._cap = None
        if tag == "ul" and self.nav_depth:
            self.ul_depth = max(0, self.ul_depth - 1)
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


def site_checks(site: Path, pages: dict[str, dict], errors: list[str]) -> tuple[int, int]:
    html = sorted(site.rglob("*.html"))
    parsed = {p: read_page(p) for p in html}
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
                target_doc = parsed.get(target) or read_page(target)
                if fragment not in target_doc.ids:
                    errors.append(f"{source.relative_to(site)}: missing fragment {raw}")

    nav_paths = set()
    for href in set().union(*(d.nav_links for d in parsed.values())):
        target, _ = local_target(site, site / "index.html", href)
        if target:
            try:
                nav_paths.add(target.relative_to(site).as_posix())
            except ValueError:
                pass
        if any(part in urlparse(href).path for part in FORBIDDEN_NAV):
            errors.append(f"unpublished page appears in navigation: {href}")
    expected = {page_url(rel, p["meta"]) for rel, p in pages.items() if p["meta"].get("nav_exclude", "").lower() != "true"}
    for page in sorted(expected - nav_paths):
        errors.append(f"navigation is missing {page}")
    index = parsed.get(site / "index.html")
    if index is not None and index.top_nav != SECTIONS:
        errors.append(f"sidebar sections are {index.top_nav}, expected {SECTIONS}")

    for d in INTERNAL_DIRS:
        if (site / d).is_dir() and any((site / d).rglob("*.md")):
            errors.append(f"internal folder {d}/ was rendered into the Pages site")
    for md in site.rglob("*.md"):
        errors.append(f"Markdown source leaked into the site: {md.relative_to(site)}")
    for old, target in REDIRECTS.items():
        path = site / old
        url = redirect_url(target)
        if not path.is_file():
            errors.append(f"missing legacy URL redirect: {old}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Page moved" not in text or url not in text:
            errors.append(f"legacy URL does not redirect to {url}: {old}")
    return checked, len(html)


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--write-redirects"]:
        write_redirects()
        return 0
    errors, pages, total = source_checks()
    print(f"source: {len(pages)} published pages, {total} prose words (budget {TOTAL_BUDGET}); nav sections {SECTIONS}")
    if args:
        site = Path(args[0]).resolve()
        if not (site / "index.html").is_file():
            print(f"missing built site: {site}", file=sys.stderr)
            return 2
        checked, n_html = site_checks(site, pages, errors)
        print(f"built site: checked {checked} links across {n_html} HTML pages")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("docs checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
