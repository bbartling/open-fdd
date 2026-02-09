#!/usr/bin/env python3
"""
Generate Brick TTL for heat pumps from equipment catalog.
Each heat pump gets: sat (discharge), zt (zone temp), fan_status.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.analyst.config import AnalystConfig, default_analyst_config


def build_brick_ttl(
    catalog_path: Path,
    site_name: str = "Creekside Elementary",
) -> str:
    """Build Brick TTL content for heat pumps."""
    cat = pd.read_csv(catalog_path)
    equipment = cat.groupby("equipment_id").first().reset_index()

    ttl = f"""@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ofdd: <http://openfdd.local/ontology#> .
@prefix : <http://openfdd.local/sp_creekside#> .

:site_1 a brick:Site ;
    rdfs:label "{site_name}" .

"""

    for _, row in equipment.iterrows():
        eq_id = row["equipment_id"]
        label = row["equipment_label"].replace('"', '\\"')
        hp_id = f":{eq_id}"
        ttl += f"""{hp_id} a brick:Heat_Pump ;
    rdfs:label "{label}" ;
    brick:isPartOf :site_1 ;
    ofdd:equipmentType "Heat_Pump" .

:{eq_id}_sat a brick:Supply_Air_Temperature_Sensor ;
    rdfs:label "sat" ;
    brick:isPointOf {hp_id} ;
    ofdd:mapsToRuleInput "sat" .

:{eq_id}_zt a brick:Zone_Temperature_Sensor ;
    rdfs:label "zt" ;
    brick:isPointOf {hp_id} ;
    ofdd:mapsToRuleInput "zt" .

:{eq_id}_fan_status a brick:Supply_Fan_Status ;
    rdfs:label "fan_status" ;
    brick:isPointOf {hp_id} ;
    ofdd:mapsToRuleInput "fan_status" .

"""
    return ttl


def run_brick_model(config: AnalystConfig | None = None) -> None:
    """Generate Brick TTL file."""
    cfg = config or default_analyst_config()
    equipment_catalog = cfg.equipment_catalog
    brick_ttl = cfg.brick_ttl
    data_root = cfg.data_root

    if not equipment_catalog.exists():
        raise FileNotFoundError(
            f"Run ingest.py and to_dataframe.py first. Missing {equipment_catalog}"
        )

    ttl = build_brick_ttl(equipment_catalog, site_name=cfg.site_name)
    data_root.mkdir(parents=True, exist_ok=True)
    brick_ttl.write_text(ttl, encoding="utf-8")
    print(f"Brick TTL saved: {brick_ttl}")


if __name__ == "__main__":
    run_brick_model()
