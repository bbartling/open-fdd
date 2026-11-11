"""The engine adapter interface: how any engine proves "pack SQL on my database == pandas".

An adapter loads a parity ``Dataset`` into your engine, runs the pack's rule SQL, and returns rows in the contract
shape. Nothing else is required: ``pip install open-fdd`` is enough.

    class MyAdapter:
        name = "my-engine"

        def load(self, dataset):                  # dataset.to_engine_input(): history, weather, authorizedSeries, ...
            self.db = open_db(); ingest(self.db, dataset.to_engine_input())

        def run(self, rule_ids=None):             # {rule_id: [{"equipment_id": ..., "fault_hours": ...}, ...]}
            return {rid: self.db.query(rule_sql(rid)) for rid in (rule_ids or all_rule_ids())}

        def close(self):
            self.db.close()

    verdict = compare(run_adapter(MyAdapter(), ds), reference(ds), Policy.default())

Row shape per rule = the rule's ``output_columns`` in ``sql/fdd/tuning_catalog.json`` (``equipment_id`` and
``fault_hours`` for the fault rules; the per-sensor sweep rules also return ``series_id``, ``sensor_role`` and
``covered_hours``). Numbers are plain floats, NULL is ``None``.
"""
from __future__ import annotations

from typing import Iterable, Protocol, Sequence, runtime_checkable

from open_fdd.parity.dataset import Dataset


@runtime_checkable
class EngineAdapter(Protocol):
    """load -> run -> close. ``run`` may be called more than once between ``load`` and ``close``."""

    name: str

    def load(self, dataset: Dataset) -> None: ...

    def run(self, rule_ids: Sequence[str] | None = None) -> dict[str, list[dict]]: ...

    def close(self) -> None: ...


def run_adapter(adapter: EngineAdapter, dataset: Dataset, rule_ids: Sequence[str] | None = None) -> dict[str, list[dict]]:
    """``load`` + ``run`` + ``close`` (``close`` always runs)."""
    try:
        adapter.load(dataset)
        return adapter.run(rule_ids)
    finally:
        adapter.close()


def conformance_errors(adapter: EngineAdapter, dataset: Dataset, rule_ids: Iterable[str]) -> list[str]:
    """Problems with the adapter's output shape (empty list = conforms). Runs ``load``/``run``/``close`` itself."""
    wanted = list(rule_ids)
    problems: list[str] = []
    for attr in ("name", "load", "run", "close"):
        if not hasattr(adapter, attr):
            problems.append(f"missing {attr}")
    if problems:
        return problems
    try:
        rows = run_adapter(adapter, dataset, wanted)
    except Exception as exc:  # noqa: BLE001
        return [f"load/run raised {type(exc).__name__}: {exc}"]
    if not isinstance(rows, dict):
        return [f"run() returned {type(rows).__name__}, expected dict"]
    for rid in wanted:
        if rid not in rows:
            problems.append(f"{rid}: no result (an empty list is fine, a missing rule is not)")
            continue
        if not isinstance(rows[rid], list):
            problems.append(f"{rid}: expected a list of rows")
            continue
        for r in rows[rid]:
            if not isinstance(r, dict) or "equipment_id" not in r:
                problems.append(f"{rid}: row without equipment_id: {r!r}")
                break
            fh = r.get("fault_hours")
            if fh is not None and (isinstance(fh, bool) or not isinstance(fh, (int, float))):
                problems.append(f"{rid}: fault_hours must be a number or None, got {fh!r}")
                break
    extra = sorted(set(rows) - set(wanted))
    if extra:
        problems.append(f"results for rules that were not requested: {extra[:5]}")
    return problems
