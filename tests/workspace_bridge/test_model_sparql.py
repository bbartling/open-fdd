"""BRICK model queries must use rdflib SPARQL on synced TTL (not JSON/grep fallbacks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def sparql_model_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    model = {
        "sites": [{"id": "demo", "name": "Bench"}],
        "equipment": [
            {
                "id": "bench-ahu",
                "name": "Bench AHU",
                "brick_type": "AHU",
                "site_id": "demo",
                "bacnet_device_instance": 5007,
                "feeds": ["bench-vav"],
            },
            {
                "id": "bench-vav",
                "name": "Bench VAV",
                "brick_type": "VAV",
                "site_id": "demo",
                "bacnet_device_instance": 42,
            },
        ],
        "points": [
            {
                "id": "bench-sat",
                "name": "SAT",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "equipment_id": "bench-ahu",
                "site_id": "demo",
                "external_id": "demo#local#bacnet#5007-analog-input-1",
                "fdd_input": "Supply_Air_Temperature_Sensor",
            },
        ],
    }
    (data / "model.json").write_text(json.dumps(model), encoding="utf-8")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    from openfdd_bridge.ttl_service import TtlService

    TtlService().sync()
    return data


def test_query_equipment_via_sparql(sparql_model_env):
    from openfdd_bridge.model_sparql import query_equipment, query_model_graph

    rows = query_equipment("demo")
    assert len(rows) >= 2
    ids = {r["equipment_id"] for r in rows}
    assert "bench-ahu" in ids or "bench_ahu" in ids or any("ahu" in i.lower() for i in ids)

    graph = query_model_graph("demo")
    assert graph["query_engine"] == "sparql"
    assert graph["feeds"]
    assert graph["points_by_equipment"].get("bench-ahu") or graph["points_by_equipment"].get("bench_ahu")


def test_query_model_tree_sparql(sparql_model_env):
    from openfdd_bridge.model_sparql import query_model_tree

    tree = query_model_tree()
    assert tree["query_engine"] == "sparql"
    assert len(tree["points"]) >= 1
    assert "Supply_Air_Temperature_Sensor" in tree["brick_types"]


def test_load_graph_from_disk_not_build_only(sparql_model_env):
    from openfdd_bridge.ttl_graph import load_graph
    from openfdd_bridge.ttl_service import TtlService

    ttl = TtlService()
    path = ttl.ttl_path
    assert path.is_file()
    graph = load_graph(ttl)
    assert len(graph) > 0
