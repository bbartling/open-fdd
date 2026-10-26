from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_WITH_CENTRAL = (
    ROOT / "docker/compose.react.yml",
    ROOT / "docker/compose.central.yml",
)
HISTORIAN_ENV = ("OPENFDD_QUERY_MEMORY_MB",)
RETIRED_HISTORIAN_ENV = (
    "OPENFDD_PARQUET_FLUSH_ROWS",
    "OPENFDD_PARQUET_FLUSH_SECONDS",
    "OPENFDD_PARQUET_TARGET_FILE_MB",
    "OPENFDD_COMPACTION_ENABLED",
    "OPENFDD_COMPACTION_MIN_FILES",
    "OPENFDD_DATAFUSION_SPILL_DIR",
)


def test_central_compose_recipes_forward_historian_tuning() -> None:
    for path in COMPOSE_WITH_CENTRAL:
        text = path.read_text()
        for name in HISTORIAN_ENV:
            assert f"{name}: ${{{name}:-" in text, f"{path}: missing {name}"
        for name in RETIRED_HISTORIAN_ENV:
            assert name not in text, f"{path}: retired Parquet/DataFusion env {name}"


def test_mqtt_compose_recipes_use_single_certs_mount_for_acl() -> None:
    for path in COMPOSE_WITH_CENTRAL:
        text = path.read_text()
        assert "../deploy/mqtt/certs:/mosquitto/certs:ro" in text
        assert "/mosquitto/config/acl" not in text
        assert "../deploy/mqtt/acl" not in text

    assert "acl_file /mosquitto/certs/acl" in (
        ROOT / "services/mqtt/mosquitto.conf"
    ).read_text()
