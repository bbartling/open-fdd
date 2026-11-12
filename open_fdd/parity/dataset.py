"""Deterministic SI parity datasets: ``generate(seed, equips, days, profile)``.

The ``basic`` profile is a faithful port of ``nf-app/tests/fixtures/synthetic_dataset.js`` (the data the in-repo parity
suite has always used); ``tests/parity/test_generator_equivalence.py`` runs both generators and asserts the rows are
identical. The ``edge`` profile is ``basic`` plus input-handling stress: null runs, a long gap, timestamp jitter,
duplicate rows, out-of-order rows, a DST-transition week and planted faults with known windows.

Only the standard library is used here. Every value is SI (degC, Pa, L/s, kW, ...); fractions are 0-1, statuses
0/1 and humidity is %RH, as declared by the input contract (``role_scales.json``).

Seeds: seed 0 is the data the JS generator produces (its only "seed" is a hash of each column name). Other seeds salt
that hash (and, for ``basic``, move the series start by whole weeks), so they are different but structurally identical datasets. The
known-difference list is validated on seed 0 only.
"""
from __future__ import annotations

import hashlib
import json
import math
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable, Iterator

from open_fdd.parity._fdlibm import sin as _sin  # V8's sin, bit for bit (math.sin differs by 1 ulp on some inputs)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Bump when ``generate`` changes its output for any (profile, seed, equips, days). Published hashes are per version.
GENERATOR_VERSION = 1

PROFILES = ("basic", "edge")
EDGE_FEATURES = ("nulls", "planted", "gap", "jitter", "duplicates", "out_of_order")
SITE_ID = "site-1"
STEP_SECONDS = 300

# ---- the input contract's scales (mirror of the constants in synthetic_dataset.js) ------------------------------------
_STATUS = frozenset(["fan_status", "pump_status", "chw_pump_status", "chiller_status", "compressor_status", "clg_available",
                     "loop_enabled", "building_ahu_load_satisfied", "building_zone_load_satisfied"])
_PERCENT = frozenset(["fan_cmd", "damper_cmd", "damper_pct", "oa_damper_pct", "clg_valve_pct", "htg_valve_pct",
                      "reheat_valve_pct", "chw_pump_cmd", "cw_pump_cmd", "return_fan", "chiller_cmd", "tower_fan_cmd"])
_HUMIDITY = frozenset(["oa_h", "ra_h", "zone_rh", "ma_h", "sa_h"])

_SENSOR_UNITS = [("oa_t", "°C"), ("mat", "°C"), ("zone_t", "°C"), ("rat", "°C"), ("sat", "°C"),
                 ("chw_supply_t", "°C"), ("chw_return_t", "°C"), ("hw_supply_t", "°C"), ("hw_return_t", "°C"),
                 ("oa_h", "%"), ("ra_h", "%"), ("zone_rh", "%"), ("ma_h", "%"), ("sa_h", "%"), ("duct_static", "Pa")]
_PLANT_SENSOR_UNITS = [("chw_flow", "L/s"), ("chw_dp", "Pa"), ("cw_supply_t", "°C"), ("cw_return_t", "°C"),
                       ("chiller_power", "kW")]

_SCALE_UNIT = {"si:degC": "°C", "si:Pa": "Pa", "si:L/s": "L/s", "si:kW": "kW", "si:kWh": "kWh", "si:A": "A",
               "si:ppm": "ppm", "si:count": "count", "percent_rh": "%", "fraction": "fraction", "boolean": "bool"}


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def history_columns() -> list[dict]:
    """The SQL input contract's history columns (without equipment_id / timestamp_utc): ``{name, type}``."""
    return [dict(c) for c in _load("parity_contract.json")["history_columns"]]


def role_map() -> dict[str, str]:
    """SQL history column -> Haystack role the pandas rules read (``role_map.json`` plus the weather roles)."""
    return {**_load("role_map.json"), "web_oa_t": "web-outside-air-temp", "web_oa_dp": "web-outside-air-dewpoint",
            "web_wb_t": "web-outside-air-wetbulb"}


# ---- the signal model (a line-by-line port of synthetic_dataset.js) -------------------------------------------------

def _js_round(x: float) -> float:
    """JavaScript ``Math.round`` (half up), unlike Python's banker's rounding."""
    f = math.floor(x)
    return float(f + 1 if x - f >= 0.5 else f)


def _wave(i: float, period: float, phase: float = 0.0) -> float:
    return _sin((2 * math.pi * i) / period + phase)


def _square(i: int, period: int, duty: float = 0.5) -> int:
    return 1 if (i % period) / period < duty else 0


def _hash_code(s: str, salt: int) -> int:
    h = (7 + 1009 * salt) % 100003
    for ch in s:
        h = (h * 31 + ord(ch)) % 100003
    return h


class _Signals:
    """Value of history column ``col`` for equipment index ``e`` at step ``i`` (hour-of-day h, occupied flag occ)."""

    def __init__(self, salt: int):
        self.salt = salt
        self._hash: dict[str, int] = {}

    def _seed(self, col: str) -> int:
        v = self._hash.get(col)
        if v is None:
            v = self._hash[col] = _hash_code(col, self.salt)
        return v

    def signal(self, col, e, i, h, occ, step):
        v = self.base(col, e, i, h, occ, step)
        if e != 1 or v is None:
            return v
        d = i % 288
        if 100 <= d < 180:
            if col == "fan_cmd":
                return 1
            if col == "mat":
                return v - 8.333333333333
            if col == "htg_valve_pct":
                return 1
            if col == "sat":
                return v - 6.666666666667
            if col == "chw_return_t":
                return self.base("chw_supply_t", e, i, h, occ, step) + 0.555555555556
            if col in ("chw_pump_status", "pump_status", "chw_pump_cmd"):
                return 1
            if col == "duct_static":
                return 124.42
        if 200 <= d < 260:
            if col in ("oa_damper_pct", "damper_pct", "damper_cmd"):
                return 0
            if col == "mat":
                return self.base("oa_t", e, i, h, occ, step) + 0.111111111111
            if col == "fan_cmd":
                return 0.8
            if col == "sat":
                return 21.111111111111
            if col == "sat_sp":
                return 12.777777777778
        return v

    def base(self, col, e, i, h, occ, step):
        v = self.percent(col, e, i, h, occ, step)
        return v / 100 if v is not None and col in _PERCENT else v

    def percent(self, col, e, i, h, occ, step):  # noqa: C901 - one flat table, like the JS switch
        sick = e == 1
        seed = self._seed(col)
        w = _wave
        oa = 8.888888888889 + 13.333333333333 * w(h, 24, -2.2) + 1.111111111111 * w(i, 17)
        if col == "oa_t": return oa
        if col == "web_oa_t": return None if e == 0 else oa + (5 if 120 < i % 288 < 200 else 0.222222222222)
        if col == "web_oa_dp": return None if e == 0 else oa - 6.666666666667
        if col == "web_wb_t": return oa - 2.777777777778
        if col == "oa_h": return 55 + 30 * w(h, 24, 1)
        if col == "rat": return 22.222222222222 + 0.444444444444 * w(i, 40)
        if col == "zone_t":
            if sick:
                return 22.222222222222 + 3.888888888889 * w(i, 150) + (0 if occ else -3.333333333333)
            return 22.222222222222 + 0.833333333333 * w(i, 60)
        if col == "zone_air_temp_sp": return 22.222222222222 if occ else 18.888888888889
        if col == "cooling_sp": return 23.888888888889
        if col == "heating_sp": return 20.555555555556
        if col == "mat":
            return (0.3 * oa + 0.7 * (22.222222222222 + 0.444444444444 * w(i, 40))
                    + (3.333333333333 * _square(i, 90, 0.3) if sick else 0))
        if col == "sat":
            if sick:
                return 12.777777777778 + 5.555555555556 * w(i, 70) + 2.222222222222 * w(i, 7)
            return 12.777777777778 + 0.666666666667 * w(i, 50)
        if col == "sat_sp": return 12.777777777778 if occ else 15.555555555556
        if col == "ahu_sat": return 12.777777777778 + 0.555555555556 * w(i, 55)
        if col == "preheat_leave_t": return 10 + 2.777777777778 * w(i, 90)
        if col == "fan_cmd":
            if not occ: return 0
            return 80 if sick else 65 + 20 * w(i, 120)
        if col == "fan_status":
            d = i % 288
            if not occ:
                return 1 if sick and 40 < d < 70 else 0
            return 0 if sick and 130 < d < 190 else 1
        if col == "damper_cmd":
            if not occ: return 0
            return 10 if sick else 20 + 70 * abs(w(i, 180))
        if col == "damper_pct":
            if not occ: return 0
            return 10 if sick else 20 + 68 * abs(w(i, 180))
        if col == "oa_damper_pct":
            if not occ: return 0
            return 10 if sick else 15 + 80 * abs(w(i, 200))
        if col == "duct_static":
            return 149.304 + 49.768 * w(i, 30) if sick else 373.26 + 24.884 * w(i, 45)
        if col == "duct_static_sp": return 373.26
        if col == "static_reset_request": return _js_round(3 * abs(w(i, 160)))
        if col == "clg_valve_pct":
            if sick: return 30 + 60 * abs(w(i, 110))
            return 40 * abs(w(i, 220)) if occ else 0
        if col == "htg_valve_pct":
            if occ: return 30 * max(0, w(i, 260, 3))
            return 25 if sick else 0
        if col == "reheat_valve_pct":
            return 70 * _square(i, 96, 0.5) if sick else 20 * max(0, w(i, 150))
        if col == "vav_discharge_t": return 14.444444444444 + 6.666666666667 * _square(i, 80, 0.35)
        if col == "vav_inlet_t": return 12.777777777778 + 1.111111111111 * w(i, 70)
        if col == "vav_total_flow": return 424.7523 + 188.7788 * w(i, 100)
        if col == "zone_flow":
            return 56.63364 + 14.15841 * w(i, 90) if sick else 117.98675 + 37.75576 * w(i, 130)
        if col == "min_flow_sp": return 70.79205
        if col == "zone_co2": return 600 + 400 * abs(w(i, 140)) + (150 if occ else 0)
        if col == "cooling_coil_entering_temp": return 15.555555555556 + 1.666666666667 * w(i, 50)
        if col == "cooling_coil_leaving_temp":
            return 12.777777777778 + 1.111111111111 * w(i, 50) + (2.222222222222 if sick else 0)
        if col == "heating_coil_entering_temp": return 12.777777777778 + 1.666666666667 * w(i, 66)
        if col == "heating_coil_leaving_temp": return 23.888888888889 + 2.222222222222 * w(i, 66)
        if col == "chw_supply_t": return 6.666666666667 + 1.111111111111 * w(i, 95)
        if col == "chw_return_t": return 11.111111111111 + 1.666666666667 * w(i, 95, 0.4)
        if col == "chw_supply_sp": return 6.666666666667
        if col == "chw_dp": return 68947.57 + 20684.271 * w(i, 85)
        if col == "chw_dp_sp": return 75842.327
        if col == "chw_flow": return 18.92706 + 7.570824 * w(i, 120)
        if col == "chw_reset_request_sum": return _js_round(4 * abs(w(i, 210)))
        if col == "hw_supply_t": return 65.555555555556 + 6.666666666667 * w(i, 130)
        if col == "hw_return_t": return 54.444444444444 + 4.444444444444 * w(i, 130, 0.3)
        if col == "hw_reset_request_sum": return _js_round(3 * abs(w(i, 190)))
        if col == "cw_supply_t": return None if e == 0 else 26.666666666667 + 2.222222222222 * w(i, 100)
        if col == "electric_kw": return 40 + 15 * w(i, 288, 0.5)
        if col == "kwh": return (40 + 15 * w(i, 288, 0.5)) * step / 3600
        if col == "electric_kwh": return None
        if col in ("chiller_amps", "chiller_current"): return 80 + 30 * w(i, 100)
        if col == "chiller_power": return 100 + 35 * w(i, 100)
        if col == "ra_h": return 45 + 5 * w(i, 80)
        if col == "zone_rh": return 48 + 8 * w(i, 120)
        if col == "ma_h": return 50 + 5 * w(i, 90)
        if col == "sa_h": return 70 + 5 * w(i, 60)
        if col in _STATUS:
            return _square(i + (seed % 50), 60 + (seed % 90), 0.5 + (0.2 if sick else 0)) * (1 if occ else 0.0)
        if col in _PERCENT: return 50 + 45 * w(i, 60 + (seed % 120), seed)
        if col in _HUMIDITY: return 50 + 15 * w(i, 90 + (seed % 50), seed)
        return 50 + 20 * w(i, 97 + (seed % 60), seed % 7)


# ---- DST (America/Chicago) without a tz database ----------------------------------------------------------------------

def _nth_sunday(year: int, month: int, n: int) -> int:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    return 1 + (6 - first.weekday()) % 7 + 7 * (n - 1)


def chicago_offset_hours(ts_ms: int) -> int:
    """UTC offset of America/Chicago at a UTC instant: -6 (CST) or -5 (CDT). US rule: DST runs from 02:00 local on
    the second Sunday of March (08:00 UTC) to 02:00 local on the first Sunday of November (07:00 UTC)."""
    year = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).year
    start = datetime(year, 3, _nth_sunday(year, 3, 2), 8, tzinfo=timezone.utc).timestamp() * 1000
    end = datetime(year, 11, _nth_sunday(year, 11, 1), 7, tzinfo=timezone.utc).timestamp() * 1000
    return -5 if start <= ts_ms < end else -6


# ---- deterministic PRNG for the edge profile (stable across Python versions) -----------------------------------------
_MASK = (1 << 64) - 1


class _Rng:
    """splitmix64, seeded from (seed, label)."""

    def __init__(self, seed: int, label: str):
        self.s = (seed * 0x9E3779B97F4A7C15 + zlib.crc32(label.encode("utf-8"))) & _MASK

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & _MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n


def _ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


# ---- the dataset ------------------------------------------------------------------------------------------------------

@dataclass
class Dataset:
    """SI long-format samples + Haystack model + role map. ``history`` is the engine-input (wide) form; ``samples()``
    yields the same data in long format."""

    seed: int
    equips: int
    days: int
    profile: str
    step_seconds: int
    history_columns: list[dict]
    history: list[dict]
    weather: list[dict]
    authorized_series: list[dict]
    series: list[dict]
    equipment: list[dict]
    utility_monthly: list[dict]
    utility_interval: list[dict]
    model: dict
    role_map: dict
    units: dict
    faults: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # -- views --------------------------------------------------------------------------------------------------------
    @cached_property
    def sensor_history(self) -> list[dict]:
        """One row per (series, history row): the per-sensor sweep input, derived from ``history`` and ``series``."""
        by_equip: dict[str, list[dict]] = {}
        for row in self.history:
            by_equip.setdefault(row["equipment_id"], []).append(row)
        out = []
        for s in self.series:
            for row in by_equip.get(s["equipment_id"], []):
                out.append({"equipment_id": s["equipment_id"], "series_id": s["series_id"], "sensor_role": s["role"],
                            "unit": s["unit"], "ts": row["ts"], "value": row.get(s["role"])})
        return out

    def samples(self) -> Iterator[tuple[str, str, int, float | str | None]]:
        """Long format: ``(equipment_id, column, ts_ms_utc, value)``, one per history cell, in row order."""
        names = [c["name"] for c in self.history_columns]
        for row in self.history:
            for n in names:
                yield row["equipment_id"], n, row["ts"], row.get(n)

    def to_engine_input(self) -> dict:
        """The ``input`` object of ``nf-app/hooks/lib/engines.js`` ``load()`` (same keys as synthetic_dataset.js)."""
        return {"historyColumns": self.history_columns, "history": self.history, "weather": self.weather,
                "authorizedSeries": self.authorized_series, "sensorHistory": self.sensor_history,
                "equipment": self.equipment, "utilityMonthly": self.utility_monthly,
                "utilityInterval": self.utility_interval}

    def to_loader_json(self) -> dict:
        """Compact engine input: ``sensorHistory`` is replaced by ``series`` (the loader expands it from ``history``)."""
        d = self.to_engine_input()
        del d["sensorHistory"]
        d["sensorSeries"] = self.series
        return d

    # -- identity -----------------------------------------------------------------------------------------------------
    def canonical(self) -> dict:
        """What the content hash covers: everything except ``sensor_history`` (derived from history + series)."""
        return {"generator": GENERATOR_VERSION, "seed": self.seed, "equips": self.equips, "days": self.days,
                "profile": self.profile, "step_seconds": self.step_seconds, "history_columns": self.history_columns,
                "history": self.history, "weather": self.weather, "authorized_series": self.authorized_series,
                "series": self.series, "equipment": self.equipment, "utility_monthly": self.utility_monthly,
                "utility_interval": self.utility_interval, "model": self.model, "role_map": self.role_map,
                "faults": self.faults, "meta": self.meta}

    def content_hash(self) -> str:
        """sha256 hex of the canonical serialization (sorted keys, compact, floats by repr, -0.0 as 0.0)."""
        blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          default=_json_default, allow_nan=False)
        return hashlib.sha256(blob.encode("ascii")).hexdigest()

    def key(self) -> str:
        return f"{self.profile}/{self.seed}/{self.equips}/{self.days}"


def _json_default(o):  # pragma: no cover - only reached for unexpected types
    raise TypeError(f"not serializable: {type(o).__name__}")


def published_hashes() -> dict[str, str]:
    """The content hashes shipped with this package version, keyed ``profile/seed/equips/days``."""
    return dict(_load("parity_hashes.json")["hashes"])


def _unit_for(scale: str | None) -> str | None:
    return _SCALE_UNIT.get(scale or "")


def _build_model(equipment_ids, cols, rmap, timezone_name) -> dict:
    scales = _load("role_scales.json")["roles"]
    points = []
    for eid in equipment_ids:
        for c in cols:
            n = c["name"]
            points.append({"equipment_id": eid, "column": n, "role": rmap.get(n, n), "scale": scales.get(n),
                           "unit": _unit_for(scales.get(n))})
    return {"site": {"id": SITE_ID, "name": "Parity site", "timezone": timezone_name},
            "equipment": [{"id": eid, "site_id": SITE_ID, "kind": "ahu"} for eid in equipment_ids], "points": points}


def generate(seed: int = 0, equips: int = 2, days: int = 3, profile: str = "basic", *, step_seconds: int = STEP_SECONDS,
             gaps: bool = False, duplicate_role: bool = False, plant_sensors: bool = False,
             edge_features: Iterable[str] | None = None) -> Dataset:
    """Build a deterministic SI parity dataset.

    ``gaps`` / ``duplicate_role`` / ``plant_sensors`` are the options of the JS generator (``synthetic_dataset.js``);
    the defaults are what the parity and stress runs use. Equipment index 1 (and every odd one) is the "sick" unit
    with injected fault windows, index 0 is mostly healthy.

    ``edge_features`` (diagnostic, ``edge`` only): restrict the input-handling stress to a subset of ``EDGE_FEATURES``
    to bisect a divergence. The default (all features) is the published ``edge`` profile.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    if seed < 0 or equips < 1 or days < 1:
        raise ValueError("seed >= 0, equips >= 1 and days >= 1 are required")
    edge = profile == "edge"
    cols = history_columns()
    rmap = role_map()
    sig = _Signals(seed)
    # basic starts Monday 2026-01-05 00:00 UTC; edge starts Friday 2026-03-06 so a 3+ day run crosses the US DST change
    t0 = _ms(2026, 3, 6) if edge else _ms(2026, 1, 5) + seed * 7 * 86400 * 1000  # edge stays put: the DST date is fixed
    steps = round((days * 86400) / step_seconds)

    def clock(i: int) -> tuple[int, float, bool]:
        ts = t0 + i * step_seconds * 1000
        if edge:  # local hour (America/Chicago): occupancy and the outdoor wave follow the wall clock, not UTC
            h = (((ts / 1000) / 3600) + chicago_offset_hours(ts)) % 24
        else:
            h = math.fmod((i * step_seconds) / 3600, 24)
        return ts, h, 6 <= h < 20

    ids = [f"AHU-{e + 1}" for e in range(equips)]
    per_equip: list[list[dict]] = []
    for e in range(equips):
        rows = []
        for i in range(steps):
            if gaps and e % 2 == 1 and 400 <= i < 440:
                continue
            ts, h, occ = clock(i)
            row: dict[str, Any] = {"equipment_id": ids[e], "ts": ts}
            for c in cols:
                n = c["name"]
                if c["type"] == "text":
                    row[n] = ("Occupied" if occ else "Unoccupied") if e == 0 else ("1.0" if occ else "0.0")
                else:
                    v = sig.signal(n, e, i, h, occ, step_seconds)
                    row[n] = None if v is None else _js_round(v * 1e6) / 1e6
            if e == 0 and i % 97 == 5:
                row["sat"] = None
                row["mat"] = None
            rows.append(row)
        per_equip.append(rows)

    faults: list[dict] = []
    meta: dict[str, Any] = {"t0_ms": t0, "steps": steps}
    if edge:
        feats = set(EDGE_FEATURES if edge_features is None else edge_features)
        if not feats <= set(EDGE_FEATURES):
            raise ValueError(f"unknown edge feature(s) {sorted(feats - set(EDGE_FEATURES))}")
        faults, edge_meta = _apply_edge(per_equip, ids, steps, step_seconds, seed, feats)
        meta.update(edge_meta)
        meta["dst"] = {"zone": "America/Chicago", "offset_before_h": -6, "offset_after_h": -5,
                       "transition_utc": "2026-03-08T08:00:00Z", "transition_ms": _ms(2026, 3, 8) + 8 * 3600 * 1000,
                       "in_range": t0 <= _ms(2026, 3, 8) + 8 * 3600 * 1000 < t0 + steps * step_seconds * 1000}
    history = [row for rows in per_equip for row in rows]

    weather = []
    for i in range(0, steps, 4):  # every 20 min at 5 min history
        ts, h, _ = clock(i)
        oa = 8.888888888889 + 13.333333333333 * _wave(h, 24, -2.2)
        weather.append({"ts": ts, "oa_t": oa, "web_oa_t": oa + 0.333333333333, "web_oa_dp": oa - 6.111111111111})

    sensor_units = list(_SENSOR_UNITS) + (list(_PLANT_SENSOR_UNITS) if plant_sensors else [])
    authorized, series, equipment = [], [], []
    for eid in ids:
        equipment.append({"building_id": SITE_ID, "equipment_id": eid})
        for role, unit in sensor_units:
            authorized.append({"site_id": SITE_ID, "equipment_id": eid, "role": role, "unit": unit})
        for role, unit in sensor_units:
            series.append({"equipment_id": eid, "series_id": f"series-{eid}-{role}", "role": role, "unit": unit})
        if duplicate_role:
            series.append({"equipment_id": eid, "series_id": f"series-{eid}-sat-duplicate", "role": "sat", "unit": "°C"})
    if duplicate_role:  # duplicate role: excluded by the rule
        authorized.append({"site_id": SITE_ID, "equipment_id": ids[0], "role": "sat", "unit": "°C"})

    utility_monthly = [{"billing_period": "2026-01", "kwh": 5000.0}, {"billing_period": "2026-02", "kwh": 100.0}]
    utility_interval = []
    for i in range(0, steps, 3):
        utility_interval.append({"ts": t0 + i * step_seconds * 1000, "kwh": 3.3 + 1.2 * _wave(i, 288)})

    units = {a["role"]: a["unit"] for a in authorized}
    model = _build_model(ids, cols, rmap, "America/Chicago" if edge else "UTC")
    ds = Dataset(seed=seed, equips=equips, days=days, profile=profile, step_seconds=step_seconds,
                 history_columns=[{"name": c["name"], "type": "text" if c["type"] == "text" else "double"} for c in cols],
                 history=history, weather=weather, authorized_series=authorized, series=series, equipment=equipment,
                 utility_monthly=utility_monthly, utility_interval=utility_interval, model=model, role_map=rmap,
                 units=units, faults=faults, meta=meta)
    return _normalize(ds)


def _normalize(ds: Dataset) -> Dataset:
    """Floats are floats and -0.0 is 0.0, so the content hash does not depend on how a value was computed."""
    def fix(v):
        if isinstance(v, bool) or v is None or isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            f = float(v)
            return 0.0 if f == 0.0 else f
        return v

    for row in ds.history:
        for k, v in row.items():
            if k not in ("equipment_id", "ts"):
                row[k] = fix(v)
    for r in ds.weather:
        for k in ("oa_t", "web_oa_t", "web_oa_dp"):
            r[k] = fix(r[k])
    for r in ds.utility_interval:
        r["kwh"] = fix(r["kwh"])
    for r in ds.utility_monthly:
        r["kwh"] = fix(r["kwh"])
    return ds


# ---- the edge profile -----------------------------------------------------------------------------------------------

_NULL_COLS = ("mat", "rat", "zone_t", "oa_h", "duct_static")


def _apply_edge(per_equip, ids, steps, step_seconds, seed, feats):
    """Mutate the per-equipment row lists in place (see the module docstring). Returns (faults, meta)."""
    rng = _Rng(seed, "edge")
    faults: list[dict] = []
    stats = {"null_cells": 0, "gap_rows_removed": 0, "gaps": [], "duplicates": 0, "swaps": 0, "jitter_s": 60}
    step_ms = step_seconds * 1000
    for e, rows in enumerate(per_equip):
        # 1. null runs (NULL cells, several samples long)
        for r in range(3 if "nulls" in feats else 0):
            col = _NULL_COLS[(e + r) % len(_NULL_COLS)]
            length = 6 + rng.below(15)
            start = rng.below(max(1, steps - length))
            for i in range(start, min(steps, start + length)):
                if rows[i][col] is not None:
                    rows[i][col] = None
                    stats["null_cells"] += 1
        # 2. planted faults with known windows (applied after the nulls, so they are intact)
        if steps >= 120 and "planted" in feats:
            start = int(steps * 0.15) + e % 3
            length = 48
            hold = next((rows[i]["sat"] for i in range(start, start + length) if rows[i]["sat"] is not None), None)
            if hold is not None:
                for i in range(start, start + length):
                    rows[i]["sat"] = hold
                faults.append({"id": f"flatline-{ids[e]}", "equipment_id": ids[e], "column": "sat", "kind": "flatline",
                               "value": hold, "start_ms": rows[start]["ts"], "end_ms": rows[start + length - 1]["ts"] + step_ms})
            start = int(steps * 0.65) + e % 3
            length = 24
            for i in range(start, start + length):
                rows[i]["zone_t"] = 80.0
            faults.append({"id": f"out-of-range-{ids[e]}", "equipment_id": ids[e], "column": "zone_t", "kind": "out_of_range",
                           "value": 80.0, "start_ms": rows[start]["ts"], "end_ms": rows[start + length - 1]["ts"] + step_ms})
        # 3. a 3 h hole (longer than 2 h) on every even unit
        if e % 2 == 0 and steps >= 288 and "gap" in feats:
            g0, glen = int(steps * 0.42), 36
            stats["gaps"].append({"equipment_id": ids[e], "start_ms": rows[g0]["ts"], "end_ms": rows[g0 + glen]["ts"]})
            stats["gap_rows_removed"] += glen
            del rows[g0:g0 + glen]
        # 4. timestamp jitter, +-60 s
        for row in rows if "jitter" in feats else ():
            row["ts"] += (rng.below(121) - 60) * 1000
        # 5. exact duplicate rows
        out = []
        for row in rows:
            out.append(row)
            if "duplicates" in feats and rng.below(150) == 0:
                out.append(dict(row))
                stats["duplicates"] += 1
        rows[:] = out
        # 6. out-of-order rows: swap a row with the one two places later
        k = 0
        while k < len(rows) - 2:
            if "out_of_order" in feats and rng.below(120) == 0:
                rows[k], rows[k + 2] = rows[k + 2], rows[k]
                stats["swaps"] += 1
                k += 3
            else:
                k += 1
    return faults, stats
