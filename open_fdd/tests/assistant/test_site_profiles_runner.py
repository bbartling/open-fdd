from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from open_fdd.assistant.site_profiles_runner import apply_site_profiles_file, load_site_profiles
from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService


def test_load_site_profiles_roundtrip(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    yml = pack / "site_profiles.yaml"
    yml.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sites": [
                    {
                        "display_name": "S",
                        "csv": {"path": "a.csv", "source": "csv"},
                        "equipment": {"name": "E", "type": "AHU"},
                        "brick_mappings": [{"external_id": "c1", "brick_type": "Outside_Air_Temperature_Sensor"}],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    data = load_site_profiles(yml)
    assert len(data["sites"]) == 1
    assert data["version"] == 1
    assert data["sites"][0]["display_name"] == "S"
    assert data["sites"][0]["csv"]["path"] == "a.csv"
    assert data["sites"][0]["csv"]["source"] == "csv"
    assert data["sites"][0]["equipment"]["name"] == "E"
    assert data["sites"][0]["equipment"]["type"] == "AHU"
    assert data["sites"][0]["brick_mappings"][0]["external_id"] == "c1"
    assert data["sites"][0]["brick_mappings"][0]["brick_type"] == "Outside_Air_Temperature_Sensor"


def test_load_site_profiles_rejects_path_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "dd"))
    pack = tmp_path / "pack"
    pack.mkdir()
    outside = tmp_path / "secret.csv"
    outside.write_text("x", encoding="utf-8")
    yml = pack / "site_profiles.yaml"
    yml.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sites": [
                    {
                        "display_name": "Bad",
                        "csv": {"path": "../secret.csv", "source": "csv"},
                        "equipment": {"name": "E", "type": "AHU"},
                        "brick_mappings": [{"external_id": "c1", "brick_type": "Outside_Air_Temperature_Sensor"}],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    model = ModelService()
    ingest = IngestService(model_service=model)
    ttl = TtlService(model_store=model.store)
    with pytest.raises(ValueError, match="must stay under profile directory"):
        apply_site_profiles_file(profiles_yaml=yml, model=model, ingest=ingest, ttl=ttl, reset=True)


def test_load_site_profiles_invalid_yaml(tmp_path: Path) -> None:
    yml = tmp_path / "bad.yml"
    yml.write_text("{ not: valid yaml [[", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_site_profiles(yml)


def test_apply_site_profiles_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyarrow")
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "dd"))
    pack = tmp_path / "pack"
    pack.mkdir()
    csvp = pack / "a.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "c1": [40.0]}).to_csv(csvp, index=False)
    yml = pack / "site_profiles.yaml"
    yml.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sites": [
                    {
                        "display_name": "Mini site",
                        "csv": {"path": "a.csv", "source": "csv"},
                        "equipment": {"name": "AHU-1", "type": "Air_Handling_Unit"},
                        "brick_mappings": [{"external_id": "c1", "brick_type": "Outside_Air_Temperature_Sensor"}],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    model = ModelService()
    ingest = IngestService(model_service=model)
    ttl = TtlService(model_store=model.store)
    out = apply_site_profiles_file(profiles_yaml=yml, model=model, ingest=ingest, ttl=ttl, reset=True)
    assert len(out["sites"]) == 1
    body = model.load()
    assert len(body["sites"]) == 1
    pts = body["points"]
    assert any(str(p.get("brick_type")) == "Outside_Air_Temperature_Sensor" for p in pts if isinstance(p, dict))
