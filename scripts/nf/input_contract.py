"""Load and validate the engine-independent SQL scratch input contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "sql/fdd/input_contract.json"

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_SCALES = {"fraction", "boolean", "percent_rh", "text"}
_SI_UNITS = {"degC", "Pa", "L/s", "kW", "kWh", "A", "ppm", "count"}
_TYPES = {"double", "text", "timestamp"}
_SQL_TYPES = {"double": "DOUBLE PRECISION", "text": "VARCHAR", "timestamp": "timestamp with time zone"}


def load_source() -> dict:
    """Return the canonical contract after checking role and relation consistency."""
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("version") != 3:
        raise ValueError(f"unsupported input contract version: {contract.get('version')!r}")
    roles = contract.get("roles")
    tables = contract.get("tables")
    if not isinstance(roles, dict) or not isinstance(tables, dict):
        raise ValueError("input_contract.json must declare roles and tables objects")
    for role, spec in roles.items():
        if not _IDENTIFIER.fullmatch(role) or not isinstance(spec, dict):
            raise ValueError(f"invalid role declaration: {role!r}")
        scale, sql_type = spec.get("scale"), spec.get("type")
        if not (scale in _SCALES or (isinstance(scale, str) and scale.startswith("si:") and scale[3:] in _SI_UNITS)):
            raise ValueError(f"{role}: invalid scale {scale!r}")
        expected_type = "text" if scale == "text" else "double"
        if sql_type != expected_type:
            raise ValueError(f"{role}: scale {scale!r} requires type {expected_type!r}, got {sql_type!r}")

    sources = contract.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"point", "input_sample"}:
        raise ValueError("input contract v3 must declare sources point and input_sample")
    view_columns = sources["input_sample"].get("columns")
    if not isinstance(view_columns, dict) or not view_columns:
        raise ValueError("sources.input_sample.columns must be a nonempty object")
    for name, spec in view_columns.items():
        if not _IDENTIFIER.fullmatch(name) or spec.get("type") not in _TYPES:
            raise ValueError(f"sources.input_sample.{name}: invalid column declaration")

    normalized = {}
    for table, declaration in tables.items():
        if not _IDENTIFIER.fullmatch(table) or not isinstance(declaration, dict):
            raise ValueError(f"invalid table declaration: {table!r}")
        columns = declaration.get("columns")
        if not isinstance(columns, dict) or not columns:
            raise ValueError(f"{table}: columns must be a nonempty object")
        normalized[table] = []
        seen = set()
        for name, spec in columns.items():
            if not _IDENTIFIER.fullmatch(name) or name in seen or not isinstance(spec, dict):
                raise ValueError(f"{table}: invalid column declaration: {name!r}")
            seen.add(name)
            sql_type = spec.get("type")
            if sql_type not in _TYPES:
                raise ValueError(f"{table}.{name}: invalid type {sql_type!r}")
            role = spec.get("role")
            if role is not None:
                if role not in roles:
                    raise ValueError(f"{table}.{name}: unknown role {role!r}")
                if roles[role]["type"] != sql_type:
                    raise ValueError(f"{table}.{name}: type differs from role {role!r}")
            normalized[table].append({"name": name, "type": sql_type, **({"role": role} if role else {})})

    history = {column["name"]: column for column in normalized.get("history", [])}
    missing = sorted(set(roles) - set(history))
    extra = sorted(set(history) - set(roles) - {"equipment_id", "timestamp_utc"})
    if missing or extra:
        raise ValueError(f"history role columns differ from roles: missing={missing}, extra={extra}")
    for role, spec in roles.items():
        if history[role].get("role") != role:
            raise ValueError(f"history.{role} must point to its declared role")
    required_tables = {"history", "weather", "utility_interval", "utility_monthly", "sensor_history"}
    if missing_tables := sorted(required_tables - set(normalized)):
        raise ValueError(f"input contract is missing required tables: {missing_tables}")
    return {**contract, "_normalized_tables": normalized}


def input_sample_signature() -> list[tuple[str, str]]:
    """The fdd.input_sample view signature every application must expose: [(column, format_type name), ...]."""
    columns = load_source()["sources"]["input_sample"]["columns"]
    names = {"double": "double precision", "text": "text", "timestamp": "timestamp with time zone"}
    return [(name, names[spec["type"]]) for name, spec in columns.items()]


def load_contract() -> dict[str, list[dict[str, str]]]:
    """Return the existing NF pack contract API: table -> typed column records."""
    return {
        table: [{"name": column["name"], "type": column["type"]} for column in columns]
        for table, columns in load_source()["_normalized_tables"].items()
    }


def postgres_type(sql_type: str) -> str:
    """Map the small contract type vocabulary to a PostgreSQL type."""
    try:
        return _SQL_TYPES[sql_type]
    except KeyError as exc:
        raise ValueError(f"unsupported scratch contract type {sql_type!r}") from exc
