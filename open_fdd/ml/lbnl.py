"""LBNL FDD data library: download a small subset into a cache and map it to Open-FDD roles (SI).

Source: Lawrence Berkeley National Laboratory, *LBNL FDD Data Sets* (single-duct AHU, simulated),
https://faultdetection.lbl.gov/data/ , DOI https://doi.org/10.25984/1881324 , licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). Granderson, Lin, Chen, Casillas, Huang, Vrabie (2022).

The archive is about 580 MB. :func:`download` reads only the members it needs with HTTP range requests
(about 30 MB compressed per file), so a subset costs a few hundred MB, not the whole zip. Files land in
:func:`default_cache_dir` (``$OPENFDD_ML_CACHE`` or ``~/.cache/open-fdd/lbnl``). Never commit them.

Units in the CSVs: temperatures °F, dampers / valves / fan commands 0-1. Duct static is not consistent
across files: in the fault-free file ``SA_SP`` is near 400 (Pa) and ``SA_SPSPT`` is 1.607 (inches of water); in
the faulted files ``SA_SP`` is in inches of water and ``SA_SPSPT`` is -400.25 (Pa, negated). :func:`to_roles`
detects the unit per file from the magnitude (see :func:`static_to_pa`).
"""

from __future__ import annotations

import io
import os
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SDAHU_ZIP_URL = (
    "https://fdddata.lbl.gov/data/Simulated_LBNL_FDD_Data_Sets_SDAHU/LBNL_FDD_Data_Sets_SDAHU.zip"
)
SDAHU_MEMBER_DIR = "LBNL_FDD_Dataset_SDAHU/"
ATTRIBUTION = (
    "Data: Lawrence Berkeley National Laboratory, LBNL FDD Data Sets, single-duct AHU (simulated), "
    "https://faultdetection.lbl.gov/data/ , DOI 10.25984/1881324, CC BY 4.0. "
    "Resampled to 5 minutes and converted to SI by open-fdd."
)

INH2O_TO_PA = 249.0889


@dataclass(frozen=True)
class LbnlFile:
    name: str
    fault: str  # "none" for the fault-free file
    intensity: str
    note: str = ""


#: The SDAHU files used by the default benchmark subset (fault-free first).
SDAHU_SUBSET: tuple[LbnlFile, ...] = (
    LbnlFile("AHU_annual.csv", "none", "fault-free"),
    LbnlFile("coi_bias_4_annual.csv", "SAT sensor bias", "+4 °C",
             "coi_bias_* in the zip = sa_bias_* in the data sheet"),
    LbnlFile("coi_bias_-4_annual.csv", "SAT sensor bias", "-4 °C",
             "coi_bias_* in the zip = sa_bias_* in the data sheet"),
    LbnlFile("oa_bias_4_annual.csv", "OAT sensor bias", "±2/±4 °C (files identical)",
             "the four oa_bias_* members are byte-identical in the published zip (same CRC-32)"),
    LbnlFile("damper_stuck_010_annual.csv", "OA damper stuck", "10 % (= minimum position)"),
    LbnlFile("damper_stuck_075_annual.csv", "OA damper stuck", "75 %"),
    LbnlFile("coi_stuck_050_annual.csv", "Cooling valve stuck", "50 %"),
    LbnlFile("coi_leakage_050_annual.csv", "Cooling valve leaking", "10-50 % (files identical)",
             "the four coi_leakage_* members are byte-identical in the published zip (same CRC-32)"),
)

FAULT_FREE = SDAHU_SUBSET[0].name

#: LBNL column -> (Open-FDD Haystack role, converter name). Only the data sheet's "basic" BAS points.
SDAHU_ROLE_MAP: dict[str, tuple[str, str]] = {
    "SA_TEMP": ("discharge-air-temp", "degF"),
    "SA_TEMPSPT": ("discharge-air-temp-sp", "degF"),
    "MA_TEMP": ("mixed-air-temp", "degF"),
    "RA_TEMP": ("return-air-temp", "degF"),
    "OA_TEMP": ("outside-air-temp", "degF"),
    "OA_DMPR_DM": ("outside-air-damper", "fraction"),
    "CHWC_VLV_DM": ("cooling-valve", "fraction"),
    "SF_CS": ("fan-cmd", "fraction"),
    "RF_CS": ("return-fan-cmd", "fraction"),
    "SF_SPD_DM": ("fan-status", "boolean"),
    "SA_SP": ("duct-static-pressure", "static"),
    "SA_SPSPT": ("duct-static-pressure-sp", "static_sp"),
    "SYS_CTL": ("occupied", "boolean"),
}


def default_cache_dir() -> Path:
    env = os.environ.get("OPENFDD_ML_CACHE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "open-fdd" / "lbnl"


class _HttpRangeFile(io.RawIOBase):
    """Seekable read-only view of a remote file through HTTP ``Range`` requests (for :mod:`zipfile`)."""

    def __init__(self, url: str, timeout: float = 120.0):
        super().__init__()
        self.url = url
        self.timeout = timeout
        self.pos = 0
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
            length = resp.headers.get("Content-Length")
            ranges = (resp.headers.get("Accept-Ranges") or "").lower()
        if not length or not length.isdigit():
            raise OSError(f"{url}: no Content-Length, cannot read the zip by ranges")
        if ranges and ranges != "bytes":
            raise OSError(f"{url}: server does not accept byte ranges")
        self.size = int(length)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def readinto(self, buffer) -> int:  # type: ignore[override]
        want = len(buffer)
        if want == 0 or self.pos >= self.size:
            return 0
        end = min(self.pos + want, self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            if resp.status != 206:
                raise OSError(f"{self.url}: expected HTTP 206 for a byte range, got {resp.status}")
            data = resp.read(end - self.pos + 2)
        if len(data) != end - self.pos + 1:
            raise OSError(f"{self.url}: range {self.pos}-{end} returned {len(data)} bytes")
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


def download(
    names: Iterable[str] | None = None,
    cache_dir: Path | str | None = None,
    *,
    url: str = SDAHU_ZIP_URL,
    force: bool = False,
    log=print,
) -> list[Path]:
    """Fetch the named SDAHU CSVs (default: :data:`SDAHU_SUBSET`) into ``cache_dir``; return their paths.

    Files already in the cache are kept unless ``force``. Only the requested zip members are transferred.
    """
    wanted = list(names) if names is not None else [f.name for f in SDAHU_SUBSET]
    cache = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    todo = [n for n in wanted if force or not (cache / n).is_file()]
    if todo:
        archive = zipfile.ZipFile(io.BufferedReader(_HttpRangeFile(url), buffer_size=8 << 20))
        for name in todo:
            target = cache / name
            tmp = target.with_suffix(target.suffix + ".part")
            if log:
                log(f"downloading {name} -> {target}")
            with archive.open(SDAHU_MEMBER_DIR + name) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 8 << 20)
            tmp.replace(target)
    for name in wanted:
        out.append(cache / name)
    return out


def static_to_pa(values, *, setpoint: bool = False):
    """Duct static to Pa, whichever unit the file used: median magnitude above 50 = Pa, else inches of water.

    A setpoint is taken as its magnitude (the faulted files store it negated).
    """
    import numpy as np

    finite = values[np.isfinite(values)]
    magnitude = float(np.median(np.abs(finite))) if len(finite) else 0.0
    out = values if magnitude > 50.0 else values * INH2O_TO_PA
    return out.abs() if setpoint else out


def _convert(values, kind: str):
    if kind == "degF":
        return (values - 32.0) / 1.8
    if kind == "static":
        return static_to_pa(values)
    if kind == "static_sp":
        return static_to_pa(values, setpoint=True)
    return values


def to_roles(raw, step_minutes: int = 5):
    """Map an LBNL SDAHU frame (``Datetime`` column or index, 1-minute rows) to SI Open-FDD roles.

    Rows are subsampled every ``step_minutes`` (a poll, not an average) onto a UTC index. The data are
    simulated with TMY weather and carry no time zone; UTC is a label only.
    """
    import pandas as pd

    frame = raw.copy()
    if "Datetime" in frame.columns:
        frame.index = pd.to_datetime(frame.pop("Datetime"))
    frame.index = pd.DatetimeIndex(frame.index)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    frame = frame.sort_index()
    if step_minutes and step_minutes > 1:
        on_grid = (frame.index.minute % int(step_minutes)) == 0
        frame = frame[on_grid]
    out = pd.DataFrame(index=frame.index)
    out.index.name = "timestamp_utc"
    for column, (role, kind) in SDAHU_ROLE_MAP.items():
        if column in frame.columns:
            out[role] = _convert(pd.to_numeric(frame[column], errors="coerce").astype(float), kind)
    out.attrs["equipment_id"] = "AHU-1"
    out.attrs["equipment_type"] = "AHU"
    out.attrs["role_units"] = {}
    return out


def load_sdahu_csv(path: Path | str, step_minutes: int = 5):
    """Read one SDAHU CSV and return :func:`to_roles` of it."""
    import pandas as pd

    raw = pd.read_csv(path, usecols=lambda c: c == "Datetime" or c in SDAHU_ROLE_MAP)
    return to_roles(raw, step_minutes=step_minutes)
