from __future__ import annotations

from pathlib import Path
import os

import pytest
import pandas as pd

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.gateway.server import create_app


def test_desktop_bridge_health() -> None:
    app = create_app()
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json().get("status") == "ok"
        docs = client.get("/docs")
        assert docs.status_code == 200
        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200


def test_desktop_bridge_sites_and_sparql() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/sites", json={"name": "Test Site"})
        assert created.status_code == 200
        site_id = created.json()["id"]
        listed = client.get("/sites")
        assert listed.status_code == 200
        assert any(s.get("id") == site_id for s in listed.json())
        sparql = client.post(
            "/data-model/testing/query",
            json={
                "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?s) AS ?count) WHERE { ?s a brick:Site . }"""
            },
        )
        assert sparql.status_code == 200
        body = sparql.json()
        assert len(body.get("rows", [])) > 0
        defaults = client.get("/rules/defaults")
        assert defaults.status_code == 200
        assert defaults.json().get("rule_pack") == "ahu_vav"
        install = client.post("/rules/defaults/install")
        assert install.status_code == 200
        attach = client.post(f"/sites/{site_id}/rule-pack", json={"rule_pack": "ahu_vav"})
        assert attach.status_code == 200
        stats = client.get("/storage/timeseries/stats")
        assert stats.status_code == 200
        ttl_status = client.get("/model/ttl/status")
        assert ttl_status.status_code == 200
        purge = client.post("/storage/timeseries/purge", json={"source": None, "site_id": None, "prune_points": False})
        assert purge.status_code == 200


def test_desktop_bridge_csv_ingest_missing_file_returns_400() -> None:
    app = create_app()
    with TestClient(app) as client:
        missing_csv = "/not/a/real/path/missing.csv"
        res = client.post(
            "/ingest/csv",
            json={
                "site_id": "site-missing",
                "source": "csv",
                "csv_path": missing_csv,
            },
        )
        assert res.status_code == 400
        detail = res.json().get("detail", "")
        assert "CSV file not found" in detail
        assert "Use an absolute file path" in detail


def test_desktop_bridge_purge_can_prune_matching_points() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/sites", json={"name": "Purge Site"})
        assert created.status_code == 200
        site_id = created.json()["id"]

        imported = client.post(
            "/model/import",
            json={
                "replace": True,
                "payload": {
                    "sites": [],
                    "equipment": [],
                    "points": [
                        {"id": "p1", "site_id": site_id, "metadata": {"source": "csv"}},
                        {"id": "p2", "site_id": site_id, "metadata": {"source": "weather"}},
                    ],
                },
            },
        )
        assert imported.status_code == 200

        purge = client.post(
            "/storage/timeseries/purge",
            json={"source": "csv", "site_id": site_id, "prune_points": True},
        )
        assert purge.status_code == 200
        purge_body = purge.json()
        assert purge_body.get("points_removed") == 1

        exported = client.get("/model/export")
        assert exported.status_code == 200
        points = exported.json().get("points", [])
        point_ids = {str(p.get("id")) for p in points}
        assert "p1" not in point_ids
        assert "p2" in point_ids


def test_desktop_bridge_model_validate_and_import_strict_payload() -> None:
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "sites": [{"id": "s1", "name": "Site 1"}],
            "equipment": [{"id": "e1", "site_id": "s1", "name": "AHU-1", "equipment_type": "AHU"}],
            "points": [{"id": "p1", "site_id": "s1", "equipment_id": "e1", "external_id": "sat"}],
        }
        validated = client.post("/model/validate", json={"payload": payload})
        assert validated.status_code == 200
        assert validated.json().get("valid") is True
        imported = client.post("/model/import", json={"replace": True, "payload": payload})
        assert imported.status_code == 200
        assert imported.json().get("sites") == 1


def test_desktop_bridge_model_validate_missing_equipment_reference() -> None:
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "sites": [{"id": "s1", "name": "Site 1"}],
            "equipment": [{"id": "e1", "site_id": "s1", "name": "AHU-1", "equipment_type": "AHU"}],
            "points": [{"id": "p1", "site_id": "s1", "equipment_id": "missing", "external_id": "sat"}],
        }
        validated = client.post("/model/validate", json={"payload": payload})
        assert validated.status_code == 200
        assert validated.json().get("valid") is False
        assert any("missing equipment_id" in issue for issue in validated.json().get("issues", []))


def test_desktop_bridge_timeseries_query_and_bounds(tmp_path: Path) -> None:
    app = create_app()
    with TestClient(app) as client:
        csv_path = tmp_path / "bridge_query.csv"
        csv_path.write_text(
        "timestamp,sat,oat\n"
        "2026-01-01T00:00:00Z,55,30\n"
        "2026-01-01T01:00:00Z,56,31\n"
        "2026-01-01T02:00:00Z,57,32\n",
        encoding="utf-8",
        )
        created = client.post("/sites", json={"name": "Query Site"})
        assert created.status_code == 200
        site_id = created.json()["id"]
        ingested = client.post(
            "/ingest/csv",
            json={"site_id": site_id, "source": "csv", "csv_path": str(csv_path)},
        )
        assert ingested.status_code == 200

        bounds = client.post("/timeseries/bounds", json={"site_id": site_id, "source": "csv"})
        assert bounds.status_code == 200
        body = bounds.json()
        assert str(body.get("start", "")).startswith("2026-01-01T00:00:00")
        assert str(body.get("end", "")).startswith("2026-01-01T02:00:00")

        queried = client.post(
            "/timeseries/query",
            json={
                "site_id": site_id,
                "sources": ["csv"],
                "start_ts": "2026-01-01T01:00:00Z",
                "end_ts": "2026-01-01T02:00:00Z",
                "columns": ["sat"],
                "limit": 10,
            },
        )
        assert queried.status_code == 200
        q = queried.json()
        assert "rows" in q
        assert len(q["rows"]) == 2


def test_desktop_bridge_weather_config_roundtrip() -> None:
    app = create_app()
    with TestClient(app) as client:
        set_resp = client.post(
            "/config/weather",
            json={
                "latitude": 42.36,
                "longitude": -71.06,
                "timezone": "America/New_York",
                "base_url": "https://archive-api.open-meteo.com/v1/archive",
            },
        )
        assert set_resp.status_code == 200
        get_resp = client.get("/config/weather")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert str(body.get("latitude")) != ""
        assert str(body.get("longitude")) != ""


def test_desktop_bridge_onboard_config_roundtrip() -> None:
    app = create_app()
    with TestClient(app) as client:
        set_resp = client.post(
            "/config/onboard",
            json={
                "base_url": "https://api.onboarddata.io",
                "building_ids": "123,456",
                "lookback_hours": 12,
                "api_key": "test-token",
                "allow_synthetic": False,
            },
        )
        assert set_resp.status_code == 200
        body = set_resp.json()
        assert str(body.get("base_url", "")).startswith("https://")
        assert str(body.get("building_ids")) == "123,456"
        assert int(body.get("lookback_hours", 0)) == 12
        assert body.get("api_key_set") is True

        get_resp = client.get("/config/onboard")
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert str(fetched.get("building_ids")) == "123,456"
        assert int(fetched.get("lookback_hours", 0)) == 12


def test_desktop_bridge_sparql_endpoints() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/sites", json={"name": "SPARQL Site"})
        assert created.status_code == 200
        text_query = """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?s) AS ?count) WHERE { ?s a brick:Site . }"""
        sparql = client.post("/data-model/sparql", json={"query": text_query})
        assert sparql.status_code == 200
        bindings = sparql.json().get("bindings", [])
        assert isinstance(bindings, list)

        files = {"file": ("check.sparql", text_query, "application/sparql-query")}
        upload = client.post("/data-model/sparql/upload", files=files)
        assert upload.status_code == 200
        assert isinstance(upload.json().get("bindings", []), list)


def test_desktop_bridge_bacnet_config_and_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    def _fake_ingest_bacnet(self, *, site_id: str, server_url: str, api_key: str = ""):
        assert site_id
        assert server_url.startswith("http")
        return {
            "rows": 1,
            "source": "bacnet",
            "success": True,
            "devices_polled": 1,
            "points_polled": 2,
        }

    monkeypatch.setattr(
        "open_fdd.desktop.services.ingest_service.IngestService.ingest_bacnet",
        _fake_ingest_bacnet,
    )

    with TestClient(app) as client:
        created = client.post("/sites", json={"name": "BACnet Site"})
        assert created.status_code == 200
        site_id = created.json()["id"]
        cfg = client.post(
            "/config/bacnet",
            json={
                "enabled": True,
                "interval_seconds": 300,
                "site_id": site_id,
                "server_url": "http://192.168.204.18:8080",
                "api_key": "token",
            },
        )
        assert cfg.status_code == 200
        body = cfg.json()
        assert body.get("enabled") is True
        assert body.get("interval_seconds") == 300
        assert body.get("api_key_set") is True

        run = client.post("/ingest/bacnet", json={"site_id": site_id})
        assert run.status_code == 200
        out = run.json()
        assert out.get("success") is True
        assert out.get("source") == "bacnet"
        health = client.get("/config/drivers/health")
        assert health.status_code == 200
        bacnet_health = health.json().get("bacnet", {})
        assert bacnet_health.get("success") is True
        assert int(bacnet_health.get("rows", 0)) >= 1


def test_desktop_bridge_driver_health_default_shape() -> None:
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/config/drivers/health")
        assert health.status_code == 200
        body = health.json()
        for key in ("csv", "weather", "bacnet", "onboard"):
            assert key in body
            assert "last_run" in body[key]
            assert "rows" in body[key]
            assert "success" in body[key]
            assert "last_error" in body[key]


def test_desktop_bridge_bacnet_ingest_requires_server_url() -> None:
    app = create_app()
    with TestClient(app) as client:
        cleared = client.post(
            "/config/bacnet",
            json={
                "enabled": False,
                "interval_seconds": 300,
                "site_id": "",
                "server_url": "",
                "api_key": "",
            },
        )
        assert cleared.status_code == 200
        created = client.post("/sites", json={"name": "BACnet Missing URL"})
        assert created.status_code == 200
        site_id = created.json()["id"]
        run = client.post("/ingest/bacnet", json={"site_id": site_id})
        assert run.status_code == 400
        assert "Missing BACnet server URL" in str(run.json().get("detail", ""))


def test_desktop_bridge_bacnet_interval_is_clamped() -> None:
    app = create_app()
    with TestClient(app) as client:
        cfg = client.post(
            "/config/bacnet",
            json={
                "enabled": True,
                "interval_seconds": 1,
                "site_id": "",
                "server_url": "http://192.168.204.18:8080",
            },
        )
        assert cfg.status_code == 200
        body = cfg.json()
        assert int(body.get("interval_seconds", 0)) >= 5


def test_desktop_bridge_bacnet_config_clears_env_when_values_blank() -> None:
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/config/bacnet",
            json={
                "enabled": True,
                "interval_seconds": 300,
                "site_id": "site-x",
                "server_url": "http://192.168.1.2:8080",
                "api_key": "token-x",
            },
        )
        cleared = client.post(
            "/config/bacnet",
            json={
                "enabled": False,
                "interval_seconds": 300,
                "site_id": "",
                "server_url": "",
                "api_key": "",
            },
        )
        assert cleared.status_code == 200
        assert os.environ.get("OFDD_BACNET_SERVER_URL") is None
        assert os.environ.get("OFDD_BACNET_SERVER_API_KEY") is None
        assert os.environ.get("OFDD_BACNET_SITE_ID") is None


def test_desktop_bridge_bacnet_interval_env_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_BACNET_POLL_INTERVAL_SECONDS", "not-an-int")
    app = create_app()
    with TestClient(app):
        assert int(app.state.bacnet_poll_interval_seconds) == 300


def test_desktop_bridge_ttl_status_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFDD_MODEL_TTL_PATH", str(tmp_path / "custom.ttl"))
    monkeypatch.setenv("OFDD_MODEL_TTL_MIRROR_PATH", str(tmp_path / "mirror" / "custom.ttl"))
    monkeypatch.setenv("OFDD_TTL_SYNC_INTERVAL_SECONDS", "5")
    app = create_app()
    with TestClient(app) as client:
        status = client.get("/model/ttl/status")
        assert status.status_code == 200
        body = status.json()
        assert str(body.get("ttl_path", "")).endswith("custom.ttl")
        assert str(body.get("ttl_mirror_path", "")).endswith("mirror\\custom.ttl") or str(
            body.get("ttl_mirror_path", "")
        ).endswith("mirror/custom.ttl")
        assert int(body.get("sync_interval_seconds", 0)) == 5


def test_rules_run_returns_400_for_missing_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()

    def _fake_load_source_frame_window(self, *, source: str, site_id: str, start_ts=None, end_ts=None):  # noqa: ARG001
        return pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00Z"],
                "supply_air_temp": [55.0],
            }
        )

    def _fake_run_rule_loop_batched(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("Rule 'x' failed (missing column?): name 'Zone_Air_Temperature_Sensor' is not defined")

    monkeypatch.setattr(
        "open_fdd.desktop.services.ingest_service.IngestService.load_source_frame_window",
        _fake_load_source_frame_window,
    )
    monkeypatch.setattr("open_fdd.gateway.server.run_rule_loop_batched", _fake_run_rule_loop_batched)

    with TestClient(app) as client:
        res = client.post(
            "/rules/run",
            json={
                "site_id": "site-a",
                "source": "csv",
                "rules_path": "dummy",
                "chunk_rows": 0,
            },
        )
        assert res.status_code == 400
        detail = str(res.json().get("detail", ""))
        assert "missing column" in detail.lower()
        assert "try source='all'" in detail.lower()


def test_data_model_predefined_queries_include_hvac_presets() -> None:
    app = create_app()
    with TestClient(app) as client:
        res = client.get("/data-model/testing/predefined")
        assert res.status_code == 200
        data = res.json()
        ids = {str(item.get("id", "")) for item in data}
        assert "plant_equipment_counts" in ids
        assert "feeds_relationships" in ids
        assert "dcv_co2_summary" in ids


def test_data_model_health_summary_endpoint_shape() -> None:
    app = create_app()
    with TestClient(app) as client:
        res = client.get("/data-model/testing/health-summary")
        assert res.status_code == 200
        body = res.json()
        assert "score" in body
        assert "counts" in body
        assert "summary" in body
        assert "orphan_equipment" in body["counts"]


def test_assistant_readiness_returns_markdown() -> None:
    app = create_app()
    with TestClient(app) as client:
        res = client.get("/assistant/readiness")
        assert res.status_code == 200
        body = res.json()
        assert "message_markdown" in body
        assert "/plots" in body.get("message_markdown", "")
        assert "plots_quicklinks" in body
        assert "deep_links" in body and "plots_fdd_csv" in body["deep_links"]
        assert body["deep_links"].get("fdd_rule_setup", "").endswith("/rule-setup")


def test_timeseries_plot_readiness_and_plots_frame_include_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    pytest.importorskip("pyarrow")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "pr_dd"))
    app = create_app()
    with TestClient(app) as client:
        site = client.post("/sites", json={"name": "pr site"})
        assert site.status_code == 200
        site_id = site.json()["id"]
        csv_path = tmp_path / "pr.csv"
        pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
                "oat": ["40.0 °F", "41.0 °F"],
            },
        ).to_csv(csv_path, index=False)
        assert client.post(
            "/ingest/csv",
            json={"site_id": site_id, "source": "csv", "csv_path": str(csv_path)},
        ).status_code == 200

        pr = client.post(
            "/timeseries/plot-readiness",
            json={"site_id": site_id, "source": "csv", "limit": 100},
        )
        assert pr.status_code == 200, pr.text
        body = pr.json()
        assert body.get("recommend_clean_metrics") is True
        assert body.get("ok") is False

        fr = client.get(
            f"/plots/frame?site_id={site_id}&source=csv&limit=100&include_readiness=true",
        )
        assert fr.status_code == 200
        fj = fr.json()
        assert "readiness" in fj
        assert fj["readiness"]["row_count"] == 2


def test_rules_export_json_put_and_parsed_query(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "rules_api_dd"))
    app = create_app()
    with TestClient(app) as client:
        empty = client.get("/rules/export-json")
        assert empty.status_code == 200
        assert empty.json().get("count") == 0

        yaml_a = "name: demo_rule\nversion: 1\nk: 1\n"
        assert client.post("/rules", json={"filename": "demo.yaml", "content": yaml_a}).status_code == 200

        snap = client.get("/rules/export-json")
        assert snap.status_code == 200
        sj = snap.json()
        assert sj["count"] == 1
        assert sj["rules"][0]["filename"] == "demo.yaml"
        assert sj["rules"][0]["yaml"] == yaml_a
        assert sj["rules"][0]["parsed"] == {"name": "demo_rule", "version": 1, "k": 1}
        assert sj["rules"][0]["parse_error"] is None

        parsed = client.get("/rules/demo.yaml", params={"parsed": True})
        assert parsed.status_code == 200
        pj = parsed.json()
        assert pj["parsed"]["name"] == "demo_rule"

        raw = client.get("/rules/demo.yaml")
        assert raw.status_code == 200
        assert raw.headers.get("content-type", "").startswith("text/plain")

        yaml_b = "name: demo_rule\nversion: 1\nk: 2\n"
        put = client.put("/rules/demo.yaml", json={"content": yaml_b})
        assert put.status_code == 200
        assert put.json().get("updated") is True

        again = client.get("/rules/export-json").json()
        assert again["rules"][0]["yaml"] == yaml_b
        assert again["rules"][0]["parsed"]["k"] == 2


def test_timeseries_clean_metrics_preview_and_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "clean_dd"))
    app = create_app()
    with TestClient(app) as client:
        site = client.post("/sites", json={"name": "clean site"})
        assert site.status_code == 200
        site_id = site.json()["id"]
        csv_path = tmp_path / "units.csv"
        pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
                "oat": ["40.0 °F", "41.2 °F"],
            },
        ).to_csv(csv_path, index=False)
        assert client.post(
            "/ingest/csv",
            json={"site_id": site_id, "source": "csv", "csv_path": str(csv_path)},
        ).status_code == 200

        prev = client.post(
            "/timeseries/clean-metrics",
            json={"site_id": site_id, "source": "csv", "commit": False, "preview_limit": 5},
        )
        assert prev.status_code == 200, prev.text
        body = prev.json()
        assert body.get("ok") is True
        assert body.get("committed") is False
        assert "oat" in (body.get("suggested_columns") or [])
        assert body.get("preview_after") and isinstance(body["preview_after"][0].get("oat"), (int, float))

        com = client.post(
            "/timeseries/clean-metrics",
            json={"site_id": site_id, "source": "csv", "commit": True, "preview_limit": 5},
        )
        assert com.status_code == 200, com.text
        assert com.json().get("committed") is True
        assert "storage_path" in com.json()


def test_assistant_apply_site_profiles_under_examples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "asst_dd"))
    ex = tmp_path / "examples"
    pack = ex / "demo_pack"
    pack.mkdir(parents=True)
    csvp = pack / "tiny.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "sat": [55.0]}).to_csv(csvp, index=False)
    yml = pack / "site_profiles.yaml"
    yml.write_text(
        """
version: 1
sites:
  - display_name: Assistant demo
    csv:
      path: tiny.csv
      source: csv
    equipment:
      name: RTU
      type: Air_Handling_Unit
    brick_mappings:
      - external_id: sat
        brick_type: Supply_Air_Temperature_Sensor
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(gateway_server, "_examples_pack_root", lambda: ex.resolve())
    app = create_app()
    with TestClient(app) as client:
        res = client.post(
            "/assistant/apply-site-profiles",
            json={"profiles_yaml": str(yml.resolve()), "reset": True},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body.get("sites")


def test_plots_fdd_frame_returns_fault_columns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "fdd_demo"))
    repo_root = Path(__file__).resolve().parents[3]
    rules_pack = default_rules_root() / "ahu_vav"
    rules_pack.mkdir(parents=True, exist_ok=True)
    ex_rule = repo_root / "examples" / "AHU" / "rules" / "sensor_bounds.yaml"
    if not ex_rule.is_file():
        pytest.skip("examples/AHU/rules not in tree")
    shutil.copy(ex_rule, rules_pack / "sensor_bounds.yaml")

    app = create_app()
    with TestClient(app) as client:
        site = client.post("/sites", json={"name": "fdd-frame site"})
        assert site.status_code == 200
        site_id = site.json()["id"]
        csv_path = tmp_path / "s.csv"
        pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
                "OAT (°F)": [40.0, 41.0],
                "SAT (°F)": [60.0, 61.0],
                "MAT (°F)": [58.0, 59.0],
                "RAT (°F)": [70.0, 71.0],
                "SA Static Press (inH₂O)": [0.5, 0.5],
            },
        ).to_csv(csv_path, index=False)
        assert client.post(
            "/ingest/csv",
            json={"site_id": site_id, "source": "csv", "csv_path": str(csv_path)},
        ).status_code == 200
        imp = client.post(
            "/model/import",
            json={
                "replace": True,
                "payload": {
                    "sites": [{"id": site_id, "name": "fdd-frame site"}],
                    "equipment": [
                        {"id": "eq1", "site_id": site_id, "name": "AHU", "equipment_type": "Air_Handling_Unit"},
                    ],
                    "points": [
                        {
                            "id": "p1",
                            "site_id": site_id,
                            "equipment_id": "eq1",
                            "external_id": "OAT (°F)",
                            "brick_type": "Outside_Air_Temperature_Sensor",
                            "fdd_input": "Outside_Air_Temperature_Sensor",
                        },
                        {
                            "id": "p2",
                            "site_id": site_id,
                            "equipment_id": "eq1",
                            "external_id": "SAT (°F)",
                            "brick_type": "Supply_Air_Temperature_Sensor",
                            "fdd_input": "Supply_Air_Temperature_Sensor",
                        },
                        {
                            "id": "p3",
                            "site_id": site_id,
                            "equipment_id": "eq1",
                            "external_id": "MAT (°F)",
                            "brick_type": "Mixed_Air_Temperature_Sensor",
                            "fdd_input": "Mixed_Air_Temperature_Sensor",
                        },
                        {
                            "id": "p4",
                            "site_id": site_id,
                            "equipment_id": "eq1",
                            "external_id": "RAT (°F)",
                            "brick_type": "Return_Air_Temperature_Sensor",
                            "fdd_input": "Return_Air_Temperature_Sensor",
                        },
                        {
                            "id": "p5",
                            "site_id": site_id,
                            "equipment_id": "eq1",
                            "external_id": "SA Static Press (inH₂O)",
                            "brick_type": "Supply_Air_Static_Pressure_Sensor",
                            "fdd_input": "Supply_Air_Static_Pressure_Sensor",
                        },
                    ],
                },
            },
        )
        assert imp.status_code == 200, imp.text

        rules = client.get("/rules")
        assert rules.status_code == 200
        rules_dir = str(rules.json().get("rules_dir", ""))
        res = client.post(
            "/plots/fdd-frame",
            json={
                "site_id": site_id,
                "rules_path": rules_dir,
                "sources": ["csv"],
                "limit": 100,
                "rule_files": ["sensor_bounds.yaml"],
                "skip_missing_columns": True,
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "bad_sensor_flag" in body.get("columns", [])
        assert body.get("fault_totals", {}).get("bad_sensor_flag") is not None


def test_plots_site_frame_returns_json_serializable_rows(tmp_path: Path) -> None:
    """Merged plot frames carry numpy dtypes; response must encode as JSON (regression for 500)."""
    pytest.importorskip("pyarrow")
    app = create_app()
    with TestClient(app) as client:
        site = client.post("/sites", json={"name": "Plot Site"})
        assert site.status_code == 200
        site_id = site.json()["id"]

        csv_a = tmp_path / "plot_a.csv"
        csv_b = tmp_path / "plot_b.csv"
        pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
                "sat": [54.0, 55.0],
            }
        ).to_csv(csv_a, index=False)
        pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
                "oat": [20.0, 21.0],
            }
        ).to_csv(csv_b, index=False)

        assert client.post(
            "/ingest/csv",
            json={"site_id": site_id, "source": "csv", "csv_path": str(csv_a)},
        ).status_code == 200
        assert client.post(
            "/ingest/csv",
            json={"site_id": site_id, "source": "weather", "csv_path": str(csv_b)},
        ).status_code == 200

        res = client.get(
            f"/plots/site-frame?site_id={site_id}&sources=csv,weather&limit=500",
        )
        assert res.status_code == 200
        body = res.json()
        assert body.get("sources") == ["csv", "weather"]
        assert "sat_csv" in body.get("columns", [])
        assert "oat_weather" in body.get("columns", [])
        assert len(body.get("rows", [])) == 2


def test_openfdd_claw_codex_poll_rejects_blank_session_id() -> None:
    app = create_app()
    with TestClient(app) as client:
        poll = client.post("/openfdd-claw/codex/device/poll", json={"session_id": "   "})
        assert poll.status_code == 422


def test_openfdd_claw_codex_start_poll_smoke() -> None:
    from unittest.mock import MagicMock, patch

    from open_fdd.gateway import codex_device_login as codex

    with patch.object(codex, "requests") as req_pkg:
        post = MagicMock()
        post.side_effect = [
            MagicMock(
                ok=True,
                status_code=200,
                text='{"device_auth_id":"da","user_code":"AB-CD","interval":1}',
            ),
            MagicMock(ok=False, status_code=403, text="{}"),
        ]
        req_pkg.post = post
        app = create_app()
        with TestClient(app) as client:
            start = client.post("/openfdd-claw/codex/device/start")
            assert start.status_code == 200
            sid = start.json()["session_id"]
            poll = client.post("/openfdd-claw/codex/device/poll", json={"session_id": sid})
            assert poll.status_code == 200
            assert poll.json()["status"] == "pending"


def test_assistant_data_model_openclaw_parses_import_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from open_fdd.gateway import openclaw_chat as oc
    from open_fdd.gateway.openclaw_chat import OpenClawChatResponse

    inner = {"sites": [{"id": "s-openclaw", "name": "S"}], "equipment": [], "points": []}
    wrapped = {"import_ready_json": inner}

    class FakeClient:
        def complete_for_task(self, **kwargs: object) -> OpenClawChatResponse:
            return OpenClawChatResponse(
                content=json.dumps(wrapped),
                raw={},
                task_class=None,
                route_reason="test",
            )

    monkeypatch.setenv("OFDD_OPENCLAW_GATEWAY_TOKEN", "test-token-for-openclaw-bridge")
    monkeypatch.setattr(oc, "OpenClawGatewayChatClient", lambda *a, **k: FakeClient())

    app = create_app()
    with TestClient(app) as client:
        inst = client.post("/rules/defaults/install")
        assert inst.status_code == 200
        res = client.post("/assistant/data-model-openclaw", json={})
        assert res.status_code == 200
        body = res.json()
        assert body.get("import_ready_parse_ok") is True
        assert body.get("import_ready") == inner
        used = body.get("rule_files_used") or []
        assert any("sensor_bounds" in str(p) for p in used)
