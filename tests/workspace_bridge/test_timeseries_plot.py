from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from openfdd_bridge.plot_readings import downsample_aligned_plot  # noqa: E402


def _reload_bridge() -> None:
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]


def _bench_model() -> dict:
    return json.loads((REPO / "workspace" / "data" / "bench_import_model.json").read_text(encoding="utf-8"))


def _bench_rules_store_path() -> Path | None:
    """Committed bench rules (workspace copy is gitignored runtime)."""
    for path in (
        REPO / "workspace" / "data" / "rules_store.json",
        REPO / "edge_config" / "demo" / "bens-office" / "rules_store.json",
    ):
        if path.is_file():
            return path
    return None


def _flat_temp_frame(rows: int = 90) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="UTC").floor("min")
    ts = pd.date_range(end - pd.Timedelta(minutes=rows - 1), periods=rows, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "oa-t": [72.0] * rows,
            "oa-h": [45.0 + (i % 3) * 0.5 for i in range(rows)],
            "duct-t": [68.0 + (i % 10) * 0.2 for i in range(rows)],
        }
    )


@pytest.fixture
def plot_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    # Copy rules store so fault eval has bench rules (CI: edge_config, local: workspace/data)
    rules_src = _bench_rules_store_path()
    if rules_src is not None:
        store = json.loads(rules_src.read_text(encoding="utf-8"))
        for rule in store.get("rules") or []:
            if isinstance(rule, dict) and rule.get("id") == "bench-oa-t-flatline-1h":
                rule["enabled"] = True
        (data / "rules_store.json").write_text(json.dumps(store, indent=2), encoding="utf-8")
    rules_py = REPO / "workspace" / "data" / "rules_py"
    if rules_py.is_dir():
        import shutil

        shutil.copytree(rules_py, data / "rules_py", dirs_exist_ok=True)
    _reload_bridge()
    from openfdd_bridge.feather_store import FeatherStore as FS  # noqa: E402
    from openfdd_bridge.model_service import ModelService as MS  # noqa: E402

    MS().import_json(_bench_model(), replace=True)
    FS().write_shard(_flat_temp_frame(), source="bacnet", site_id="demo")
    yield data


def test_downsample_aligned_plot():
    n = 100
    ts = [str(i) for i in range(n)]
    series = {"oa-t": [float(i) for i in range(n)]}
    faults = {"rule-a": [1 if i > 50 else 0 for i in range(n)]}
    out_ts, out_series, out_faults, stride, truncated = downsample_aligned_plot(n, 20, ts, series, faults)
    assert truncated is True
    assert len(out_ts) <= 20
    assert len(out_series["oa-t"]) == len(out_ts)
    assert len(out_faults["rule-a"]) == len(out_ts)
    assert stride >= 1


def test_evaluate_fault_plots_flatline(plot_env: Path):
    _reload_bridge()
    from openfdd_bridge.feather_store import FeatherStore as FS  # noqa: E402
    from openfdd_bridge.model_service import ModelService as MS  # noqa: E402
    from openfdd_bridge.plot_readings import evaluate_fault_plots as eval_faults  # noqa: E402

    model = MS().load()
    df = FS().read_site("demo", source="bacnet")
    assert df is not None
    plots, panels, totals = eval_faults(df, "demo", model)
    assert panels
    assert "bench-oa-t-flatline-1h" in plots
    assert len(plots["bench-oa-t-flatline-1h"]) == len(df)
    assert totals["bench-oa-t-flatline-1h"] >= 0


def test_read_plot_readings_dual_axis_kinds(plot_env: Path):
    _reload_bridge()
    from openfdd_bridge.plot_readings import read_plot_readings as read_plots  # noqa: E402

    payload = read_plots(
        "demo",
        ["oa-t", "oa-h", "duct-t"],
        hours=24,
        include_faults=True,
    )
    assert payload["timestamps"]
    assert set(payload["series"].keys()) == {"oa-t", "oa-h", "duct-t"}
    assert payload["series_kinds"]["oa-h"] == "humidity"
    assert payload["series_kinds"]["oa-t"] == "temperature"
    assert payload["fault_panels"]
    assert len(payload["fault_plots"]["bench-oa-t-flatline-1h"]) == len(payload["timestamps"])


def test_readings_api(plot_env: Path):
    _reload_bridge()
    from openfdd_bridge.main import create_app as make_app  # noqa: E402

    client = TestClient(make_app())
    r = client.get(
        "/api/timeseries/readings",
        params={"site_id": "demo", "columns": "oa-t,oa-h", "hours": 24, "include_faults": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "oa-t" in body["series"]
    assert body["fault_panels"]
