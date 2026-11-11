"""In-repo engine adapters (implement open_fdd.parity.EngineAdapter).

``NodeEngineAdapter("pglite" | "sqlite")`` runs the SQL pack through ``sql_run.mjs`` (nf-app engines: PGlite = real
Postgres, sql.js = translated SQLite) on a Python-generated dataset. TimescaleDB is not adapted here: it needs a server
and loads from a live NF history, not from a dataset.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def node() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("node is required for the SQL side (nf-app engines)")
    return exe


class NodeEngineAdapter:
    """load(dataset) writes the loader JSON; run(rule_ids) spawns ``sql_run.mjs`` for this engine only."""

    def __init__(self, kind: str):
        if kind not in ("pglite", "sqlite"):
            raise ValueError(kind)
        self.kind = kind
        self.name = kind
        self._dir: Path | None = None
        self._ds_file: Path | None = None
        self.stats: dict = {}
        self.raw: dict = {}

    def load(self, dataset) -> None:
        self.close()
        self._dir = Path(tempfile.mkdtemp(prefix=f"parity_{self.kind}_"))
        self._ds_file = self._dir / "dataset.json"
        self._ds_file.write_text(json.dumps(dataset.to_loader_json(), ensure_ascii=False), encoding="utf-8")

    def run(self, rule_ids: Sequence[str] | None = None, rule_sql: dict | None = None) -> dict[str, list[dict]]:
        if self._ds_file is None:
            raise RuntimeError("load(dataset) before run()")
        out = self._dir / "out.json"
        cmd = [node(), str(HERE / "sql_run.mjs"), "--dataset", str(self._ds_file), "--out", str(out), "--engines", self.kind]
        if rule_ids:
            cmd += ["--rules", ",".join(rule_ids)]
        if rule_sql:
            f = self._dir / "rule_sql.json"
            f.write_text(json.dumps(rule_sql), encoding="utf-8")
            cmd += ["--rule-sql", str(f)]
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"sql_run.mjs failed:\n{proc.stdout}\n{proc.stderr}")
        self.raw = json.loads(out.read_text(encoding="utf-8"))
        self.stats = {"wall_s": time.time() - t0, "timing": self.raw["timing"], "memory": self.raw["memory"],
                      "errors": self.raw["errors"]}
        return self.raw["results"][self.kind]

    def close(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = self._ds_file = None


ADAPTERS = {"pglite": lambda: NodeEngineAdapter("pglite"), "sqlite": lambda: NodeEngineAdapter("sqlite")}
