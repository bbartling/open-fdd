"""Site pack isolation — no Acme rules on bench, no cross-site CSV rows."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))


@pytest.fixture
def bench_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    data = ws / "data"
    comm = ws / "bacnet" / "commissioning"
    data.mkdir(parents=True)
    comm.mkdir(parents=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))

    pack = tmp_path / "pack"
    pack.mkdir()
    model = {
        "sites": [{"id": "demo", "name": "Bench"}],
        "equipment": [{"id": "bench-1", "site_id": "demo", "name": "Bench"}],
        "points": [
            {
                "id": "5007-analog-input-1173",
                "site_id": "demo",
                "equipment_id": "bench-1",
                "brick_type": "Zone_Air_Temperature_Sensor",
            }
        ],
    }
    (pack / "model.json").write_text(json.dumps(model), encoding="utf-8")
    (pack / "rules_store.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "bench-oa-t-flatline-1h",
                        "bindings": {"point_ids": ["5007-analog-input-1173"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (pack / "points.csv").write_text(
        "device_instance,device_address,object_type,object_instance,object_name,description,"
        "present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,"
        "poll_interval_s,point_id,series_id\n"
        "5007,2000:7,analog-input,1173,OA-T,,70,degF,demo,bens-office,,,,1,60,"
        "5007-analog-input-1173,demo#bens-office#unknown#5007-analog-input-1173\n",
        encoding="utf-8",
    )
    (pack / "commission.env").write_text(
        "SITE_ID=demo\nBUILDING_ID=bens-office\n", encoding="utf-8"
    )
    return pack


def test_validate_rejects_acme_rule_on_bench_pack(bench_pack: Path) -> None:
    from openfdd_bridge.site_pack import SitePackRef, validate_pack

    bad = bench_pack / "rules_store.json"
    doc = json.loads(bad.read_text(encoding="utf-8"))
    doc["rules"].append({"id": "acme-zn-t-flatline-1h", "bindings": {"point_ids": []}})
    bad.write_text(json.dumps(doc), encoding="utf-8")
    ref = SitePackRef(site_id="demo", building_id="bens-office")
    errors = validate_pack(ref, bench_pack, forbid_acme_rules=True)
    assert any("acme" in e.lower() for e in errors)


def test_apply_site_writes_model_and_rules(bench_pack: Path) -> None:
    from openfdd_bridge.site_pack import SitePackRef, apply_site

    ref = SitePackRef(site_id="demo", building_id="bens-office")
    applied = apply_site(ref, pack_root=bench_pack, sync_ttl=False)
    assert "model.json" in applied
    model = json.loads((Path(applied["model.json"])).read_text(encoding="utf-8"))
    assert model["sites"][0]["id"] == "demo"
    rules = json.loads((Path(applied["rules_store.json"])).read_text(encoding="utf-8"))
    assert all(not str(r.get("id", "")).startswith("acme-") for r in rules.get("rules", []))


def test_purge_foreign_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from openfdd_bridge.rule_store import RuleStore
    from openfdd_bridge.site_pack import purge_foreign_rules

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    store = RuleStore(path=data / "rules_store.json")
    store._save(
        {
            "version": 1,
            "rules": [
                {"id": "bench-oa-t-flatline-1h"},
                {"id": "acme-zn-t-flatline-1h"},
            ],
        }
    )
    removed = purge_foreign_rules()
    assert removed == 1
    ids = [r["id"] for r in store.list_rules()]
    assert "bench-oa-t-flatline-1h" in ids
    assert "acme-zn-t-flatline-1h" not in ids
