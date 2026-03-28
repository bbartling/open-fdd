import json
from pathlib import Path
from typing import Any

import requests

API = "http://192.168.204.16:8000"
BACNET = "http://192.168.204.16:8080"
ENV_FILE = Path(r"C:\Users\ben\OneDrive\Desktop\BensOpenClawTesting\.env")
FIXTURE = Path(r"C:\Users\ben\.openclaw\workspace\open-fdd-develop-v2.0.10\openclaw\bench\fixtures\demo_site_llm_payload.json")
REPORT = Path(r"C:\Users\ben\OneDrive\Desktop\testing\automated_testing\reports\ai-modeling-pass-2026-03-28.md")


def load_key() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OFDD_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("OFDD_API_KEY missing in desktop env")


HEADERS = {"Authorization": f"Bearer {load_key()}"}


def j(method: str, path: str, **kwargs) -> Any:
    r = requests.request(method, API + path, headers=HEADERS, timeout=60, **kwargs)
    r.raise_for_status()
    if r.content:
        return r.json()
    return None


def delete_all_sites() -> list[str]:
    out = []
    sites = j("GET", "/sites")
    for s in sites:
        sid = s["id"]
        requests.delete(API + f"/sites/{sid}", headers=HEADERS, timeout=60).raise_for_status()
        out.append(s["name"])
    return out


def reset_everything() -> dict:
    deleted = delete_all_sites()
    reset = j("POST", "/data-model/reset")
    return {"deleted_sites": deleted, "reset": reset}


def create_site(name: str) -> dict:
    return j("POST", "/sites", json={"name": name})


def import_fixture_with_feeds(site_id: str) -> dict:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    body["equipment"] = [
        e for e in body.get("equipment", []) if e.get("equipment_name") in {"AHU-1", "VAV-1", "Weather-Station"}
    ]
    for p in body["points"]:
        p["site_id"] = site_id
        p["site_name"] = None
    for e in body.get("equipment", []):
        e["site_id"] = site_id
    return j("PUT", "/data-model/import", json=body)


def discover(device_instance: int) -> dict:
    return j(
        "POST",
        "/bacnet/point_discovery_to_graph",
        json={"instance": {"device_instance": device_instance}, "update_graph": True, "write_file": True},
    )


def export_rows() -> list[dict]:
    data = j("GET", "/data-model/export")
    return data["value"] if isinstance(data, dict) and "value" in data else data


def check() -> dict:
    return j("GET", "/data-model/check")


def sparql(query: str) -> Any:
    return j("POST", "/data-model/sparql", json={"query": query})


def read_property(device_instance: int, device_address: str, obj: str) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": device_instance,
        "method": "client_read_property",
        "params": {
            "request": {
                "device_instance": device_instance,
                "device_address": device_address,
                "object_identifier": obj,
                "property_identifier": "present-value",
            }
        },
    }
    r = requests.post(BACNET + "/client_read_property", json=body, timeout=30)
    r.raise_for_status()
    return r.json()


NAME_MAP = {
    "DAP-P": ("AHU-1", "Supply_Air_Static_Pressure_Sensor", "duct_static", "inH2O", True),
    "SA-T": ("AHU-1", "Supply_Air_Temperature_Sensor", "ahu_sat", "degF", True),
    "MA-T": ("AHU-1", "Mixed_Air_Temperature_Sensor", "mat", "degF", True),
    "RA-T": ("AHU-1", "Return_Air_Temperature_Sensor", "rat", "degF", True),
    "SA-FLOW": ("AHU-1", "Supply_Air_Flow_Sensor", "airflow", "cfm", True),
    "OA-T": ("AHU-1", "Outside_Air_Temperature_Sensor", "oat", "degF", True),
    "ELEC-PWR": ("AHU-1", "Power_Sensor", "power", "kW", True),
    "SF-O": ("AHU-1", "Supply_Fan_Command", "sf_cmd", "%", True),
    "HTG-O": ("AHU-1", "Heating_Valve_Command", "htg_cmd", "%", True),
    "CLG-O": ("AHU-1", "Cooling_Valve_Command", "clg_cmd", "%", True),
    "DPR-O": ("AHU-1", "Damper_Position_Command", "damper_cmd", "%", True),
    "DAP-SP": ("AHU-1", "Supply_Air_Static_Pressure_Setpoint", "duct_static_sp", "inH2O", True),
    "SAT-SP": ("AHU-1", "Supply_Air_Temperature_Setpoint", "ahu_sat_sp", "degF", True),
    "OAT-NETWORK": ("AHU-1", "Outside_Air_Temperature_Sensor", "oat", "degF", True),
    "SF-S": ("AHU-1", "Supply_Fan_Status", "sf_status", "binary", True),
    "SF-C": ("AHU-1", "Supply_Fan_Command", "sf_cmd", "binary", True),
    "Occ-Schedule": ("AHU-1", "Occupancy_Command", "occ", None, True),
    "ZoneTemp": ("VAV-1", "Zone_Air_Temperature_Sensor", "zone_temp", "degF", True),
    "VAVFlow": ("VAV-1", "Discharge_Air_Flow_Sensor", "airflow", "cfm", True),
    "VAVDamperCmd": ("VAV-1", "Damper_Position_Command", "damper_cmd", "%", True),
    "ZoneCoolingSpt": ("VAV-1", "Zone_Air_Cooling_Temperature_Setpoint", "zone_clg_sp", "degF", True),
    "ZoneDemand": ("VAV-1", "Cooling_Demand_Sensor", "clg_demand", "%", True),
    "VAVFlowSpt": ("VAV-1", "Discharge_Air_Flow_Setpoint", "airflow_sp", "cfm", True),
}


def tag_export_rows(rows: list[dict], site_id: str) -> dict:
    points: list[dict] = []
    seen = set()
    for row in rows:
        key = (row.get("bacnet_device_id"), row.get("object_identifier"), row.get("external_id"))
        if key in seen:
            continue
        seen.add(key)
        out = dict(row)
        out["site_id"] = site_id
        out["site_name"] = None
        name = row.get("object_name") or row.get("external_id")
        if name in NAME_MAP:
            eq, brick_type, rule_input, unit, polling = NAME_MAP[name]
            out["equipment_name"] = eq
            out["brick_type"] = brick_type
            out["rule_input"] = rule_input
            out["unit"] = unit
            out["polling"] = polling
        else:
            out["equipment_name"] = out.get("equipment_name")
            out["brick_type"] = None
            out["rule_input"] = None
            out["unit"] = None
            out["polling"] = False
        points.append(out)
    equipment = [
        {"equipment_name": "AHU-1", "equipment_type": "Air_Handling_Unit", "site_id": site_id, "feeds": ["VAV-1"]},
        {"equipment_name": "VAV-1", "equipment_type": "Variable_Air_Volume_Box", "site_id": site_id, "fed_by": ["AHU-1"]},
    ]
    return {"points": points, "equipment": equipment}


def main() -> None:
    report: list[str] = ["# AI data modeling pass — 2026-03-28", ""]

    # Pass 1: direct prompt-shaped import on clean graph
    report.append("## Pass 1 — clean reset + prompt-shaped import with feeds/fed_by")
    report.append(f"Reset: `{json.dumps(reset_everything())}`")
    site1 = create_site("AI-LLM-Prompt-Pass-1")
    report.append(f"Created site 1: `{site1['name']}` / `{site1['id']}`")
    imp1 = import_fixture_with_feeds(site1["id"])
    report.append(f"Import result: `{json.dumps(imp1)}`")
    check1 = check()
    report.append(f"Graph check: `{json.dumps(check1)}`")
    rows1 = export_rows()
    report.append(f"Export rows after import: `{len(rows1)}`")

    feeds_q = '''
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?src ?dst WHERE {
  ?src brick:feeds ?dst .
}
'''
    feeds1 = sparql(feeds_q)
    report.append(f"feeds query result: ```json\n{json.dumps(feeds1, indent=2)}\n```")

    # Pass 2: reset, discovery to graph, export, tag per prompt, import back
    report.append("")
    report.append("## Pass 2 — clean reset + BACnet discovery -> export -> prompt-style tagging -> import")
    report.append(f"Reset: `{json.dumps(reset_everything())}`")
    site2 = create_site("AI-LLM-Prompt-Pass-2")
    report.append(f"Created site 2: `{site2['name']}` / `{site2['id']}`")
    d1 = discover(3456789)
    d2 = discover(3456790)
    report.append(f"Discovery 3456789 ok={d1.get('ok')} write_ok={d1.get('write_ok')}")
    report.append(f"Discovery 3456790 ok={d2.get('ok')} write_ok={d2.get('write_ok')}")
    discovered_rows = export_rows()
    report.append(f"Export rows after discovery: `{len(discovered_rows)}`")
    tagged = tag_export_rows(discovered_rows, site2['id'])
    report.append(f"Tagged payload summary: points={len(tagged['points'])}, equipment={len(tagged['equipment'])}")
    imp2 = j('PUT', '/data-model/import', json=tagged)
    report.append(f"Import tagged payload: `{json.dumps(imp2)}`")
    check2 = check()
    report.append(f"Graph check after discovery+import: `{json.dumps(check2)}`")
    rows2 = export_rows()
    report.append(f"Export rows after import-back: `{len(rows2)}`")
    feeds2 = sparql(feeds_q)
    report.append(f"feeds query result after import-back: ```json\n{json.dumps(feeds2, indent=2)}\n```")

    bacnet_points_q = '''
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?point ?obj ?equip WHERE {
  ?point bacnet:object-identifier ?obj .
  OPTIONAL { ?equip brick:hasPoint ?point }
}
ORDER BY ?equip ?obj
'''
    report.append(f"BACnet point query: ```json\n{json.dumps(sparql(bacnet_points_q), indent=2)}\n```")

    live1 = read_property(3456789, '192.168.204.13', 'analog-input,2')
    live2 = read_property(3456790, '192.168.204.14', 'analog-input,1')
    report.append(f"Live BACnet read SA-T: `{json.dumps(live1)}`")
    report.append(f"Live BACnet read ZoneTemp: `{json.dumps(live2)}`")

    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(REPORT)


if __name__ == '__main__':
    main()
