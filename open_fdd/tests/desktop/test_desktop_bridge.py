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
