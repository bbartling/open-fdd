from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_cloud_recipes_do_not_boot_fieldbus_or_priority_scanner() -> None:
    for relative in ("docker/compose.central.yml", "docker/compose.csv.yml"):
        text = (ROOT / relative).read_text()
        assert "openfdd-fieldbus" not in text, relative
        assert "fieldbus:" not in text, relative
        assert "OPENFDD_PRIORITY_SCAN_" not in text, relative


def test_ot_recipes_persist_edge_history_and_keep_scheduler_opt_in() -> None:
    for relative in (
        "docker/compose.edge.yml",
        "docker/compose.standalone.yml",
        "docker/compose.react.fieldbus.yml",
        "docker/compose.local-fieldbus.yml",
    ):
        text = (ROOT / relative).read_text()
        assert "OPENFDD_PRIORITY_SCAN_ENABLED: ${OPENFDD_PRIORITY_SCAN_ENABLED:-0}" in text
        assert "OPENFDD_EDGE_STORE_DIR: /edge-state" in text
        assert "/edge-state" in text


def test_cloud_docs_keep_mqtt_history_sync_explicitly_deferred() -> None:
    text = (ROOT / "docs/operations/build-recipes.md").read_text()
    assert "MQTT history synchronization is a separate future" in text
    assert "does not boot a" in text and "fieldbus scanner" in text
