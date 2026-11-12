"""In-repo engine adapters (implement open_fdd.parity.EngineAdapter).

``NodeEngineAdapter("pglite" | "sqlite")`` runs the SQL pack through ``sql_run.mjs`` (nf-app engines: PGlite = real
Postgres, sql.js = translated SQLite) on a Python-generated dataset.

``TimescaleAdapter`` runs the same pack on a real TimescaleDB through the NEW core tables (fdd.point, fdd.input_sample,
fdd.rule_result): it needs a server (``PGURL`` = admin connection, ``OPENFDD_TS_TEST_DISPOSABLE=1``; the runner creates
and drops its own database) and is skipped by the tests when none is configured.
"""
from __future__ import annotations

import json
import os
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


def timescale_configured() -> bool:
    """True when a disposable TimescaleDB is configured for the tests (never inferred from anything else)."""
    return bool(os.environ.get("PGURL")) and os.environ.get("OPENFDD_TS_TEST_DISPOSABLE") == "1"


class TimescaleAdapter:
    """load(dataset) writes the core rows (native units); run() spawns ``nf-app/timescale/test/parity_run.mjs``.

    The runner seeds an NF-like ``public.data`` from ``to_imperial(ds).to_core_rows()`` (so the affine ``fdd.input_sample``
    view converts), syncs ``fdd.point``, loads the history, runs the pack, writes ``fdd.rule_result`` and reads the rows
    BACK from it. ``raw`` keeps the runner's whole answer (history mismatches, idempotency counts, index / signature flags).
    ``plan_only=True`` needs no database: it checks the scale / offset the loader would apply against the SI dataset.
    """

    name = "timescale"

    def __init__(self, plan_only: bool = False):
        self.plan_only = plan_only
        self._dir: Path | None = None
        self._in: Path | None = None
        self.stats: dict = {}
        self.raw: dict = {}

    def load(self, dataset) -> None:
        from open_fdd.parity import to_imperial

        self.close()
        if not self.plan_only and not timescale_configured():
            raise RuntimeError("TimescaleAdapter needs PGURL and OPENFDD_TS_TEST_DISPOSABLE=1 (a disposable TimescaleDB)")
        self._dir = Path(tempfile.mkdtemp(prefix="parity_timescale_"))
        self._in = self._dir / "input.json"
        site = "parity"
        points, samples = to_imperial(dataset).to_core_rows(site)
        columnar: dict[str, list[list]] = {}
        for _site, key, ts, value in samples:
            cols = columnar.setdefault(key, [[], []])
            cols[0].append(ts)
            cols[1].append(value)
        meta = dataset.meta
        t0, steps = meta["t0_ms"], meta["steps"]
        si_history: dict[str, list[dict]] = {}
        for row in dataset.history:
            si_history.setdefault(row["equipment_id"], []).append(row)
        self._in.write_text(json.dumps({
            "site_id": site, "step_seconds": dataset.step_seconds,
            "window": {"from_ms": t0, "to_ms": t0 + steps * dataset.step_seconds * 1000},
            "points": points, "samples": columnar, "si_history": si_history, "weather": dataset.weather,
            "history_columns": dataset.history_columns}, ensure_ascii=False), encoding="utf-8")

    def run(self, rule_ids: Sequence[str] | None = None) -> dict[str, list[dict]]:
        if self._in is None:
            raise RuntimeError("load(dataset) before run()")
        out = self._dir / "out.json"
        cmd = [node(), str(ROOT / "nf-app/timescale/test/parity_run.mjs"), "--in", str(self._in), "--out", str(out)]
        if self.plan_only:
            cmd.append("--plan-only")
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError("parity_run.mjs failed: " + proc.stdout + " " + proc.stderr)
        self.raw = json.loads(out.read_text(encoding="utf-8"))
        self.stats = {"wall_s": time.time() - t0, "timing": self.raw.get("timing", {}), "memory": self.raw.get("memory", {}),
                      "errors": self.raw.get("errors", {})}
        results = self.raw.get("results", {})
        return {r: results.get(r, []) for r in rule_ids} if rule_ids else results

    def close(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = self._in = None


ADAPTERS = {"pglite": lambda: NodeEngineAdapter("pglite"), "sqlite": lambda: NodeEngineAdapter("sqlite"),
            "timescale": lambda: TimescaleAdapter()}
