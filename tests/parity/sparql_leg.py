"""The SPARQL-client leg of the parity harness: pandas oracle == SQL pack == SPARQL data client (#1618).

A synthetic dataset (``open_fdd.parity.generate``) is served as a synthetic Normal Framework: every history column of every
equipment is an NF point (``ofddRole`` = its SQL role, unit = the column's SI unit), weather is a weather-station point,
samples are raw NF ``point/data``. The shipped hooks run over it in Node (``sparql_hook_runner.mjs``: ``sparql-data`` with
Oxigraph in its worker, the ``rdf`` model Turtle, point selection, point/time paging, byte cap, NF sample-cap split; only
NF's HTTP surface is mocked). The client then does what it does against a real box:

    open_fdd.nf.sparql_data.fetch(transport, QUERY, ...)      # every page, one model snapshot, StartHook flat args
    open_fdd.nf.sparql_data.frames(answer, weather="separate") # bind_equipment + frames_from_samples + si_plan_for
    open_fdd.nf.sparql_data.weather_frame(answer)

and the frames go through ``open_fdd.parity.pandas_ref.reference_from_frames``: the same pandas twin of every SQL rule
the oracle runs (no fault equation lives in the client or here). Its results are compared with the SQL pack under the
same ``Policy`` as the oracle (so the oracle's pinned known differences apply unchanged), and rule by rule with the
oracle itself, where the only allowed delta is float noise (see ``oracle_mismatches``).
"""
from __future__ import annotations

import json
import math
import subprocess
import uuid as _uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from open_fdd.parity.dataset import SITE_ID, Dataset

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "sparql_hook_runner.mjs"
NS = _uuid.UUID("0f0dd000-5ba2-4c11-9e00-000000001618")
WEATHER_STATION = "wx-1"

#: Every point with an explicit Open-FDD role, its uuid and role (the query a client script would ship).
QUERY = """SELECT ?uuid ?role WHERE {
  ?p a phIoT:point ;
     ref:hasExternalReference/ref:hasTimeseriesId ?uuid ;
     local:ofddRole ?role .
}"""


def point_uuid(equip: str, column: str) -> str:
    return str(_uuid.uuid5(NS, f"{equip}/{column}"))


def _markers(col: str, ds: Dataset) -> str:
    """Haystack markers as a site would model them: the dataset's registered sensors (``Dataset.units``, the SV sweep
    population of the SQL fixture) are ``sensor`` points; commands, setpoints and the other inputs are not."""
    if col in ds.units:
        return "point,his,sensor"
    if col.endswith("_cmd"):
        return "point,his,cmd"
    if col.endswith("_sp"):
        return "point,his,sp"
    return "point,his"


def nf_world(ds: Dataset) -> dict:
    """``{records, series}``: the dataset as NF model records (site, equipment, points) and raw samples per point."""
    recs: list[dict] = [{"uuid": str(_uuid.uuid5(NS, "site")), "name": "Parity site", "pointType": "SITE",
                         "attrs": {"id": SITE_ID, "dis": "Parity site"}}]
    for e in ds.equipment:
        eid = e["equipment_id"]
        recs.append({"uuid": str(_uuid.uuid5(NS, "equip/" + eid)), "name": eid, "pointType": "EQUIPMENT",
                     "attrs": {"id": eid, "siteRef": SITE_ID, "dis": eid, "markers": "equip,ahu"}})
    types = {c["name"]: c["type"] for c in ds.history_columns}
    series: dict[str, list] = {}
    for p in ds.model["points"]:
        eid, col = p["equipment_id"], p["column"]
        u = point_uuid(eid, col)
        attrs = {"siteRef": SITE_ID, "equipRef": eid, "markers": _markers(col, ds), "dis": f"{eid} {col}",
                 "kind": "Str" if types.get(col) == "text" else "Number", "ofddRole": col}
        if p.get("unit"):
            attrs["unit"] = p["unit"]
        recs.append({"uuid": u, "name": f"{eid}-{col}", "pointType": "POINT", "attrs": attrs})
        series[u] = []
    for r in ds.history:
        eid = r["equipment_id"]
        for c in ds.history_columns:
            v = r.get(c["name"])
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                series[point_uuid(eid, c["name"])].append([r["ts"], v])
    for col, unit in (("web_oa_t", "°C"), ("web_oa_dp", "°C")):
        u = point_uuid(WEATHER_STATION, col)
        recs.append({"uuid": u, "name": col, "pointType": "POINT",
                     "attrs": {"siteRef": SITE_ID, "weatherStationRef": WEATHER_STATION, "dis": col, "unit": unit,
                               "markers": "point,his,sensor,weather", "kind": "Number", "ofddRole": col}})
        series[u] = [[r["ts"], r[col]] for r in ds.weather if r.get(col) is not None]
    return {"records": recs, "series": series}


class HookProcess:
    """The shipped hooks in one Node process over a synthetic NF; ``transport(hook_id, args)`` for the client."""

    def __init__(self, world: Mapping[str, Any], cap: int = 10000):
        self.proc = subprocess.Popen(["node", str(RUNNER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, encoding="utf-8", cwd=str(HERE))
        self.calls: list[str] = []
        first = self._send({**world, "cap": cap})
        if not first.get("ok"):
            raise RuntimeError(f"hook runner failed to load the world: {first}")

    def _send(self, msg: Mapping[str, Any]) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(msg, separators=(",", ":"), allow_nan=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("hook runner exited")
        return json.loads(line)

    def transport(self, hook_id: str, args: Mapping[str, Any]) -> dict:
        from open_fdd.nf.client import hook_args

        self.calls.append(hook_id)
        return self._send({"hook": hook_id, "args": hook_args(args)})  # exactly what StartHook carries

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=30)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def client_frames(ds: Dataset, query: str = QUERY, *, source: str = "nf", **fetch_kw: Any):
    """``(answer, {equipment_id: frame}, weather_on_grid | None, calls)`` through the hooks and the client.

    ``source="nf"``: raw NF ``point/data`` samples. ``source="timescale"``: the hook's Timescale-selected path, buckets
    of the dataset's own step (``historyRoute`` over an in-memory ``history_buckets``; see the runner).
    """
    from open_fdd.nf import sparql_data as sd
    from open_fdd.parity.pandas_ref import weather_on_grid

    start, end = ds.history_window_ms()   # every device's actual first row (jitter may precede t0) and the weather
    from datetime import datetime, timezone
    t0, t1 = (datetime.fromtimestamp(x / 1000, tz=timezone.utc) for x in (start, end))
    world = {**nf_world(ds), "timescale": source == "timescale"}
    bucket = "raw" if source == "nf" else f"{ds.step_seconds // 60} minutes"
    with HookProcess(world) as hp:
        answer = sd.fetch(hp.transport, query, t0, t1, bucket=bucket, source=source, **fetch_kw)
    if answer["source"] != source:
        raise AssertionError(f"asked for source {source}, the hook answered {answer['source']}")
    calls = len(hp.calls)
    # The SV sweep population comes from the points' own metadata (the ``sensor`` marker), as on a real site; it is
    # checked against the dataset's registered sensors by ``sweep_mismatches`` instead of being overwritten here.
    fr = sd.frames(answer, weather="separate", window_sec=ds.step_seconds, sweep_marker="sensor")
    wx = sd.weather_frame(answer)
    return answer, {k[1]: v for k, v in fr.items()}, (None if wx is None else weather_on_grid(wx, ds.step_seconds)), calls


def sparql_reference(ds: Dataset, rules: Iterable[str] | None = None, **fetch_kw: Any) -> tuple[dict, dict]:
    """``(results shaped like open_fdd.parity.reference, info)`` for the SPARQL-client leg."""
    from open_fdd.parity.pandas_ref import reference_from_frames

    answer, frames, weather, calls = client_frames(ds, **fetch_kw)
    info = {"hook_calls": calls, "points": len(answer["points"]), "equipment": len(frames), "source": answer["source"],
            "samples": sum(len(s) for s in answer["series"].values()), "sweep_mismatches": sweep_mismatches(ds, frames)}
    return reference_from_frames(frames, weather, float(ds.step_seconds), rules), info


def _close(a, b, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)


def oracle_mismatches(sparql: Mapping[str, Mapping[str, dict]], oracle: Mapping[str, Mapping[str, dict]],
                      tol_h: float = 1e-9) -> list[str]:
    """Rule/equipment cells where the SPARQL client and the pandas oracle differ: status, fault hours (float noise
    ``tol_h`` hours only) and per-sensor sweep hours. Both run the same rule functions, so this should be empty."""
    bad = []
    for rule in sorted(set(oracle) | set(sparql)):
        o, s = oracle.get(rule, {}), sparql.get(rule, {})
        for e in sorted(set(o) | set(s)):
            a, b = o.get(e), s.get(e)
            if a is None or b is None:
                bad.append(f"{rule}/{e}: only in {'oracle' if b is None else 'sparql'}")
                continue
            if a["status"] != b["status"]:
                bad.append(f"{rule}/{e}: status {a['status']} != {b['status']}")
            elif not _close(a.get("pandas"), b.get("pandas"), tol_h):
                bad.append(f"{rule}/{e}: fault_hours {a.get('pandas')} != {b.get('pandas')}")
            if a.get("active_samples") != b.get("active_samples"):
                bad.append(f"{rule}/{e}: gated samples {a.get('active_samples')} != {b.get('active_samples')}")
            for k in ("pandas_sensor_fault_hours", "pandas_sensor_silence_hours"):
                x, y = a.get(k) or {}, b.get(k) or {}
                if set(x) != set(y) or any(not _close(x[r], y[r], tol_h) for r in x):
                    bad.append(f"{rule}/{e}: {k} differ")
    return bad

def sweep_mismatches(ds: Dataset, frames: Mapping[str, Any]) -> list[str]:
    """Where the client's SV sweep population or units differ from the dataset's registered sensors.

    The SQL fixture sweeps ``Dataset.units`` (role -> SI unit) on every equipment; the client must arrive at exactly
    that set from the fetched metadata, with the same SI unit, and must not sweep anything else.
    """
    from open_fdd.nf.model import column_for

    bad = []
    for eid, df in sorted(frames.items()):
        want = {column_for(r): u for r, u in ds.units.items() if u and column_for(r) in df.columns}
        got = dict(df.attrs.get("sweep_units") or {})
        if got != want:
            extra, missing = sorted(set(got) - set(want)), sorted(set(want) - set(got))
            wrong = sorted(c for c in set(got) & set(want) if got[c] != want[c])
            bad.append(f"{eid}: sweep extra={extra} missing={missing} unit={wrong}")
    return bad
