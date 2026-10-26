#!/usr/bin/env python3
"""Timescale-only product guard (WP2c).

Fails when:

1. ``cargo tree`` for the workspace (normal, build and dev edges, every target)
   lists a parquet, arrow*, datafusion* or feather* crate, or the inspection
   itself fails (non-zero exit, error text, empty package list).
2. Product Rust (``crates/*/src``, ``services/*/src``, ``edge/src``,
   ``mcp/src``; test modules and ``#[cfg(test)]`` files excluded) names a
   ``.parquet`` / ``.arrow`` / ``.feather`` / ``.ipc`` file, writes one, or
   uses a columnar crate path.
3. Product Rust outside ``crates/fdd_tsdb/src/writer.rs`` inserts, updates or
   copies into ``sample``.

``archive/`` is not scanned. Run ``--self-test`` for the positive and
negative controls.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_GLOBS = ("crates/*/src", "services/*/src", "edge/src", "mcp/src")
WRITER = "crates/fdd_tsdb/src/writer.rs"

FORBIDDEN_CRATE = re.compile(r"^(parquet[\w-]*|arrow[\w-]*|datafusion[\w-]*|feather[\w-]*) v")
CARGO_ERROR = re.compile(r"^error(\[[^\]]+\])?:", re.M)
COLUMNAR_NAME = re.compile(r"\.(parquet|arrow|feather|ipc)$", re.I)
COLUMNAR_EXTENSION_CALL = re.compile(
    r"\.(with_extension|set_extension)\(\s*\"(parquet|arrow|feather|ipc)\"", re.I
)
COLUMNAR_CRATE_PATH = re.compile(r"\b(parquet|arrow\w*|datafusion\w*|feather\w*)::")
SAMPLE_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+sample\b", re.I)
CFG_TEST = re.compile(r"#\[\s*cfg\s*\(\s*(all\s*\(\s*)?test\b")
TEST_FN_ATTR = re.compile(r"#\[\s*(tokio::)?test\b")


def lex(src: str) -> tuple[str, str, list[tuple[int, int]]]:
    """Return (code, mask, strings).

    ``code`` has comments blanked. ``mask`` also blanks string and char
    literal contents, so braces and semicolons can be matched safely.
    ``strings`` holds the (start, end) span of each string literal body.
    Offsets and newlines are preserved in both views.
    """
    code = list(src)
    mask = list(src)
    strings: list[tuple[int, int]] = []
    i, n = 0, len(src)

    def blank(view: list[str], a: int, b: int) -> None:
        for k in range(a, b):
            if view[k] != "\n":
                view[k] = " "

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(code, i, j)
            blank(mask, i, j)
            i = j
        elif src.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if src.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif src.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            blank(code, i, j)
            blank(mask, i, j)
            i = j
        elif c == "r" and re.match(r'r#*"', src[i:]) and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            hashes = len(re.match(r"r(#*)\"", src[i:]).group(1))
            start = i + 2 + hashes
            close = '"' + "#" * hashes
            j = src.find(close, start)
            j = n if j < 0 else j
            strings.append((start, j))
            blank(mask, start, j)
            i = j + len(close)
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            strings.append((i + 1, j))
            blank(mask, i + 1, j)
            i = j + 1
        elif c == "'":
            m = re.match(r"'(\\.|\\u\{[0-9a-fA-F]+\}|[^\\'])'", src[i:])
            if m:
                blank(mask, i + 1, i + len(m.group(0)) - 1)
                i += len(m.group(0))
            else:
                i += 1
        else:
            i += 1
    return "".join(code), "".join(mask), strings


def matching_brace(mask: str, open_at: int) -> int:
    depth = 0
    for k in range(open_at, len(mask)):
        if mask[k] == "{":
            depth += 1
        elif mask[k] == "}":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(mask)


def skip_attributes(mask: str, pos: int) -> int:
    while True:
        m = re.compile(r"\s*#\s*\[").match(mask, pos)
        if not m:
            return pos
        depth, k = 0, m.end() - 1
        while k < len(mask):
            if mask[k] == "[":
                depth += 1
            elif mask[k] == "]":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        pos = k + 1


PATH_ATTR = re.compile(r'#\s*\[\s*path\s*=\s*"([^"]+)"\s*\]')


def test_regions(code: str, mask: str) -> tuple[list[tuple[int, int]], list[tuple[str, str | None]]]:
    """Spans of ``#[cfg(test)]`` / ``#[test]`` items and test-only ``mod x;`` (name, ``#[path]``)."""
    regions: list[tuple[int, int]] = []
    test_mods: list[tuple[str, str | None]] = []
    for pattern in (CFG_TEST, TEST_FN_ATTR):
        for m in pattern.finditer(mask):
            item = skip_attributes(mask, m.start())
            mod_decl = re.compile(r"\s*(pub(\([^)]*\))?\s+)?mod\s+(\w+)\s*;").match(mask, item)
            if mod_decl:
                path_attr = PATH_ATTR.search(code, m.start(), item)
                test_mods.append((mod_decl.group(3), path_attr.group(1) if path_attr else None))
                regions.append((m.start(), mod_decl.end()))
                continue
            brace = mask.find("{", item)
            semi = mask.find(";", item)
            if brace < 0 or (0 <= semi < brace):
                end = len(mask) if semi < 0 else semi + 1
            else:
                end = matching_brace(mask, brace)
            regions.append((m.start(), end))
    return regions, test_mods


def child_module_paths(path: Path, name: str, path_attr: str | None) -> list[Path]:
    if path_attr is not None:
        return [path.parent / path_attr]
    base = path.parent if path.name in ("main.rs", "lib.rs", "mod.rs") else path.parent / path.stem
    return [base / f"{name}.rs", base / name / "mod.rs", base / name]


def product_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in SOURCE_GLOBS:
        for src_dir in sorted(root.glob(pattern)):
            files.extend(sorted(p for p in src_dir.rglob("*.rs") if p.is_file()))
    return files


def line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def scan_sources(root: Path) -> list[str]:
    failures: list[str] = []
    files = product_files(root)
    test_only: set[Path] = set()
    parsed: dict[Path, tuple[str, str, list[tuple[int, int]], list[tuple[int, int]]]] = {}
    for path in files:
        src = path.read_text(encoding="utf-8", errors="replace")
        code, mask, strings = lex(src)
        regions, test_mods = test_regions(code, mask)
        parsed[path] = (code, mask, strings, regions)
        for name, path_attr in test_mods:
            test_only.update(p.resolve() for p in child_module_paths(path, name, path_attr))

    def excluded(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == t or t in resolved.parents for t in test_only)

    for path, (code, mask, strings, regions) in parsed.items():
        if excluded(path):
            continue
        rel = path.relative_to(root).as_posix()

        def in_test(pos: int) -> bool:
            return any(a <= pos < b for a, b in regions)

        for a, b in strings:
            if in_test(a):
                continue
            text = code[a:b]
            if COLUMNAR_NAME.search(text.strip()):
                failures.append(f"{rel}:{line_of(code, a)}: columnar file name {text.strip()!r}")
            if SAMPLE_WRITE.search(text) and rel != WRITER:
                failures.append(
                    f"{rel}:{line_of(code, a)}: writes `sample` outside {WRITER} (use fdd_tsdb::writer)"
                )
        for pattern, label in (
            (COLUMNAR_EXTENSION_CALL, "columnar file extension"),
            (COLUMNAR_CRATE_PATH, "columnar crate path"),
        ):
            for m in pattern.finditer(code):
                if in_test(m.start()):
                    continue
                if label == "columnar crate path" and any(sa <= m.start() < sb for sa, sb in strings):
                    continue
                failures.append(f"{rel}:{line_of(code, m.start())}: {label} `{m.group(0)}`")
    return failures


def cargo_tree(root: Path, tree_file: str | None) -> tuple[int, str, str]:
    if tree_file is not None:
        text = Path(tree_file).read_text(encoding="utf-8")
        return 0, text, ""
    proc = subprocess.run(
        [
            "cargo",
            "tree",
            "--workspace",
            "-e",
            "normal,build,dev",
            "--target",
            "all",
            "--prefix",
            "none",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_cargo(root: Path, tree_file: str | None) -> list[str]:
    try:
        status, out, err = cargo_tree(root, tree_file)
    except FileNotFoundError:
        return ["cargo not found on PATH; cargo tree inspection did not run"]
    if status != 0:
        return [f"cargo tree exited {status}: {err.strip()}"]
    if CARGO_ERROR.search(err) or CARGO_ERROR.search(out):
        return [f"cargo tree reported an error: {err.strip() or out.strip()}"]
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return ["cargo tree produced no package list"]
    hits = sorted({line for line in lines if FORBIDDEN_CRATE.match(line)})
    return [f"forbidden crate in product graph: {hit}" for hit in hits]


def run(root: Path, tree_file: str | None) -> int:
    failures = check_cargo(root, tree_file) + scan_sources(root)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        print(f"forbid_columnar_product: FAILED ({len(failures)})")
        return 1
    print("forbid_columnar_product: OK")
    return 0


CLEAN_TREE = "openfdd-central v4.0.4\nsqlx v0.8.6\nanyhow v1.0.0\n"


def self_test() -> int:
    cases: list[tuple[str, bool, dict[str, str], str]] = [
        ("clean product tree", True, {}, CLEAN_TREE),
        ("cargo graph lists parquet", False, {}, CLEAN_TREE + "parquet v57.0.0\n"),
        ("cargo graph lists arrow-ipc", False, {}, CLEAN_TREE + "arrow-ipc v57.0.0\n"),
        ("cargo graph lists datafusion", False, {}, CLEAN_TREE + "datafusion v50.0.0\n"),
        ("cargo graph is empty", False, {}, ""),
        ("cargo graph has error text", False, {}, "error: simulated failure\n"),
        (
            "product writes a parquet file",
            False,
            {"crates/demo/src/lib.rs": 'pub fn w(d: &std::path::Path) { let _ = std::fs::write(d.join("part-0.parquet"), b""); }\n'},
            CLEAN_TREE,
        ),
        (
            "product sets an arrow extension",
            False,
            {"edge/src/lib.rs": 'pub fn p(d: &std::path::Path) -> std::path::PathBuf { d.join("x").with_extension("arrow") }\n'},
            CLEAN_TREE,
        ),
        (
            "product uses a columnar crate",
            False,
            {"services/central/src/main.rs": "fn main() { let _ = parquet::file::reader::SerializedFileReader::new; }\n"},
            CLEAN_TREE,
        ),
        (
            "second sample writer",
            False,
            {"services/central/src/main.rs": 'fn main() { let _q = "INSERT INTO sample (ts, site_id) VALUES ($1, $2)"; }\n'},
            CLEAN_TREE,
        ),
        (
            "sample update outside the writer",
            False,
            {"crates/demo/src/lib.rs": 'pub const Q: &str = "UPDATE sample SET val = 1";\n'},
            CLEAN_TREE,
        ),
        (
            "writer owns sample inserts; tests and comments are ignored",
            True,
            {
                WRITER: 'pub const Q: &str = "INSERT INTO sample (ts) VALUES ($1)";\n',
                "crates/demo/src/lib.rs": (
                    "// INSERT INTO sample is documented here; legacy part.parquet files are ignored.\n"
                    'pub fn ext_is(p: &str) -> bool { p.ends_with("parquet") }\n'
                    "pub const STAGE: &str = \"INSERT INTO sample_import_stage (ts) VALUES ($1)\";\n"
                    "#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {\n"
                    '        let _ = ("INSERT INTO sample (ts) VALUES (now())", "{", "history.parquet");\n'
                    "    }\n}\n"
                ),
                "services/central/src/main.rs": "#[cfg(test)]\nmod fixtures;\nfn main() {}\n",
                "services/central/src/fixtures.rs": 'pub const F: &str = "INSERT INTO sample (ts) VALUES (now())";\n',
            },
            CLEAN_TREE,
        ),
        (
            "test-only mod with #[path] is ignored",
            True,
            {
                "services/central/src/product.rs": '#[cfg(test)]\n#[path = "product_fixture.rs"]\nmod fixture;\npub fn p() {}\n',
                "services/central/src/product_fixture.rs": 'pub const F: &str = "INSERT INTO sample (ts) VALUES (now())";\n',
            },
            CLEAN_TREE,
        ),
        (
            "non-test mod with #[path] is scanned",
            False,
            {
                "services/central/src/product.rs": '#[path = "product_writer.rs"]\nmod writer;\npub fn p() {}\n',
                "services/central/src/product_writer.rs": 'pub const F: &str = "INSERT INTO sample (ts) VALUES (now())";\n',
            },
            CLEAN_TREE,
        ),
    ]
    failed = 0
    positive = negative = 0
    for name, expect_ok, files, tree in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, body in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
            tree_path = root / "cargo-tree.txt"
            tree_path.write_text(tree, encoding="utf-8")
            with open(os.devnull, "w", encoding="utf-8") as sink:
                stdout = sys.stdout
                sys.stdout = sink
                try:
                    status = run(root, str(tree_path))
                finally:
                    sys.stdout = stdout
        ok = (status == 0) == expect_ok
        kind = "positive" if expect_ok else "negative"
        if expect_ok:
            positive += 1
        else:
            negative += 1
        print(f"{'OK' if ok else 'FAIL'} {kind}: {name} (exit {status})")
        failed += 0 if ok else 1
    if failed:
        print(f"forbid_columnar_product self-test: FAILED ({failed})")
        return 1
    print(f"forbid_columnar_product self-test: OK (positive={positive} negative={negative})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true", help="run positive/negative controls")
    parser.add_argument("--cargo-tree-file", help="read cargo tree output from a file")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return run(ROOT, args.cargo_tree_file)


if __name__ == "__main__":
    sys.exit(main())
