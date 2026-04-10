"""FDD loop + column_map_resolver integration (platform lives in this repo)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("rdflib")

from openfdd_stack.platform.config import set_config_overlay
from openfdd_stack.platform.loop import run_fdd_loop

_MINIMAL_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .

<http://openfdd.local/point/sat> a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "sat" .

<http://openfdd.local/point/oat> a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "oat" .

<http://openfdd.local/equipment/ahu1> ofdd:equipmentType "AHU" .
<http://openfdd.local/equipment/vav1> ofdd:equipmentType "VAV" .
"""


def _mock_conn_no_sites():
    cur = MagicMock()
    cur.execute = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def test_run_fdd_loop_passes_ttl_path_to_custom_resolver(tmp_path):
    """Injected resolver receives the same ttl_path the loop resolves."""
    (tmp_path / "r.yaml").write_text("name: z\ntype: bounds\n")
    cfg_ttl = tmp_path / "config" / "data_model.ttl"
    cfg_ttl.parent.mkdir(parents=True)
    cfg_ttl.write_text(_MINIMAL_TTL)
    set_config_overlay({"rules_dir": str(tmp_path.resolve())})

    mock_resolver = MagicMock()
    mock_resolver.build_column_map.return_value = {}

    with patch("openfdd_stack.platform.loop.get_conn", return_value=_mock_conn_no_sites()):
        with patch("open_fdd.engine.runner.load_rules_from_dir", return_value=[]):
            with patch(
                "openfdd_stack.platform.loop.get_ttl_path_resolved",
                return_value=str(cfg_ttl),
            ):
                run_fdd_loop(column_map_resolver=mock_resolver)

    mock_resolver.build_column_map.assert_called_once()
    kw = mock_resolver.build_column_map.call_args.kwargs
    assert "ttl_path" in kw
    assert isinstance(kw["ttl_path"], Path)
    assert kw["ttl_path"].resolve() == cfg_ttl.resolve()
