#!/usr/bin/env python3
"""Read-only IP baseline capture for the 4.0.7 SI cutover (#1284).

Writes FDD results only, never telemetry: ``POST /api/fdd/run`` with
``force_new_data: true`` persists ``fdd_run`` / ``fdd_interval_result``, and
analytics calls use ``refresh: true`` (``analytics_result`` cache). Those derived
stores may grow. Telemetry tables ``sample``, ``point_map``, and
``authorized_series`` must not change — the capture aborts if their row counts
drift.

For each configured site (JWT env file + sites JSON — no site names in code):
  * SQL IP FDD: fault/covered seconds and status per rule × equipment × UTC day
    (bulk ``POST /api/fdd/run``, then ``fdd_interval_result`` UTC-hour buckets
    rolled up to UTC calendar days via ``OPENFDD_DATABASE_URL``)
  * Analytics: every shipped ``POST /api/analytics/*`` row (no truncation)
  * Pandas IP: every registry rule × site equipment with explicit
    ``pair_status`` (``computed``, ``not_applicable``, ``no_pandas_function``,
    ``error``) and daily ``fault_seconds`` / ``covered_seconds`` when computed
  * Unit inventory with W2c-style source unit (or ``unresolved`` — never a silent
    default)
  * Sample row counts + sha256 manifest under ``~/openfdd-si-cutover/baseline-<sha>-<date>/``

``OPENFDD_DATABASE_URL`` or ``--database-url`` is mandatory for capture mode.
Compose ``.env`` often points at the Timescale **container** hostname; on the
host running this script use the published port, for example
``postgresql://openfdd:PASSWORD@127.0.0.1:5432/openfdd`` (match user/db from
``.env`` / ``OPENFDD_TIMESCALE_PASSWORD``).

Login: ``--jwt-env PATH`` loads ``OPENFDD_API_BASE``, ``OPENFDD_AGENT_PASSWORD``,
and related keys into the process (values are never printed). ``--password`` wins
when passed explicitly; otherwise ``login`` uses ``OPENFDD_AGENT_PASSWORD`` from
that file or the environment.

``open_fdd`` + ``pandas`` are mandatory unless ``--skip-pandas``. Host-side DB
access needs ``psycopg[binary]`` (see ``scripts/qualification/requirements.txt``).
Exit non-zero on any ``error`` pair unless ``--allow-errors`` (recorded in the
manifest).

CI: ``--self-test`` (offline shapes); ``--emit-ip-goldens DIR`` for W0c fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
STRESS = REPO / "scripts" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from helpers import (  # noqa: E402
    HttpClient,
    add_connection_args,
    analytics_post,
    apply_base_url,
    login,
    post_sparql,
    resolve_base_url,
    safe_print,
    wait_until_ready,
)

from si_cutover.baseline_history import load_samples_in_window  # noqa: E402
from si_cutover.baseline_io import (  # noqa: E402
    JsonlGzWriter,
    validate_record_shapes,
    write_manifest,
)

POLL_SECONDS = 300.0
DEFAULT_REQUEST_TIMEOUT_S = 120.0
FDD_RUN_409_MAX_ATTEMPTS = 8
FDD_RUN_409_BACKOFF_S = 1.0
FDD_RUN_409_BACKOFF_CAP_S = 32.0

HAYSTACK_ROLE_GOLDEN = REPO / "crates" / "fdd_core" / "testdata" / "haystack_point_role_golden.json"


class UnmappedRoleError(Exception):
    """Role id from SPARQL has no entry in haystack_point_role_golden.json."""

    def __init__(self, roles: list[str], *, skip_counts: dict[str, int]) -> None:
        self.roles = roles
        self.skip_counts = skip_counts
        super().__init__(", ".join(roles))


class CaptureQualificationError(RuntimeError):
    """Capture cannot qualify as the frozen IP baseline (recorded in the manifest)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@lru_cache(maxsize=1)
def load_role_id_to_haystack() -> dict[str, str]:
    """Map canonical role ids (and Haystack names) to pandas cookbook column names."""
    raw = json.loads(HAYSTACK_ROLE_GOLDEN.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        haystack = str(pair[0]).strip()
        role_id = str(pair[1]).strip()
        if haystack and role_id:
            out.setdefault(role_id, haystack)
        if haystack:
            out.setdefault(haystack, haystack)
    return out


def resolve_haystack_column(role: str, role_map: dict[str, str]) -> str | None:
    key = str(role or "").strip()
    if not key:
        return None
    mapped = role_map.get(key)
    if mapped:
        return mapped
    normalized = key.replace("-", "_")
    if normalized != key:
        return role_map.get(normalized)
    return None


def frame_builder_empty_error(equipment_id: str, *, skip_counts: dict[str, int]) -> ValueError:
    """Distinguish missing samples from all points skipped by role mapping."""
    parts = [
        f"{name}={skip_counts[name]}"
        for name in (
            "skipped_other_equipment",
            "skipped_unbound_no_column",
            "skipped_no_role",
            "skipped_unmapped_role",
        )
        if skip_counts.get(name)
    ]
    detail = ", ".join(parts) if parts else "no bindable points"
    if skip_counts.get("skipped_no_role") and not skip_counts.get("skipped_unmapped_role"):
        msg = (
            f"all points skipped for equipment {equipment_id} ({detail}); "
            "SPARQL fdd_role_candidates returned empty canonicalRole"
        )
    else:
        msg = f"no historian samples for equipment {equipment_id} in window ({detail})"
    exc = ValueError(msg)
    exc.skip_counts = dict(skip_counts)  # type: ignore[attr-defined]
    return exc


def missing_required_roles_unmapped(
    rule: dict[str, Any],
    *,
    role_map: dict[str, str],
) -> list[str]:
    """Required registry roles with no golden Haystack mapping."""
    missing: list[str] = []
    for role in rule.get("required_roles") or []:
        rid = str(role).strip()
        if not rid:
            continue
        if resolve_haystack_column(rid, role_map) is None:
            missing.append(rid)
    return missing


def resolve_openfdd_key(equipment_id: str, column: str, explicit: str | None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    col = str(column or "").strip()
    prefix = f"{equipment_id}."
    if col.startswith(prefix):
        return col
    return f"{equipment_id}.{col}"


def _sparql_equipment_id(pt: dict[str, Any]) -> str:
    return str(pt.get("equipmentId") or pt.get("equipment_id") or "").strip()


def _explicit_openfdd_key(point: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    for key in ("openfdd_key", "history_openfdd_key", "history_key"):
        value = point.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    for container_key in ("history", "history_ref", "historyRef"):
        nested = point.get(container_key)
        if isinstance(nested, dict):
            for key in ("openfdd_key", "history_openfdd_key", "key"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
    distinct = set(candidates)
    if len(distinct) > 1:
        raise ValueError("conflicting explicit history keys in typed point binding")
    return next(iter(distinct), None)


def resolve_bound_openfdd_key(conn, *, site_id: str, equipment_id: str, point: dict[str, Any]) -> str | None:
    """Resolve explicit, exact typed IDs, or documented equipment.point key encoding."""
    explicit = _explicit_openfdd_key(point)
    point_id = str(point.get("pointId") or point.get("point_id") or "").strip()
    column = str(point.get("column") or "").strip()
    with conn.cursor() as cur:
        if explicit:
            cur.execute(
                "SELECT openfdd_key FROM point_map WHERE site_id = %s AND equipment_id = %s AND openfdd_key = %s",
                (site_id, equipment_id, explicit),
            )
            rows = cur.fetchall()
            if len(rows) != 1:
                raise ValueError("explicit history key is absent or ambiguous in point_map")
            return str(rows[0][0])
        rows = []
        if point_id:
            cur.execute(
                """SELECT DISTINCT openfdd_key FROM point_map
                   WHERE site_id = %s AND equipment_id = %s
                     AND (portal_point_id = %s OR haystack_id = %s)""",
                (site_id, equipment_id, point_id, point_id),
            )
            rows = cur.fetchall()
        if len(rows) > 1:
            raise ValueError("typed point identity maps to multiple point_map keys")
        exact_keys = {str(row[0]) for row in rows}
        canonical_candidates = sorted(
            {f"{equipment_id}.{value}" for value in (point_id, column) if value}
        )
        if canonical_candidates:
            cur.execute(
                """SELECT DISTINCT openfdd_key FROM point_map
                   WHERE site_id = %s AND equipment_id = %s AND openfdd_key = ANY(%s)""",
                (site_id, equipment_id, canonical_candidates),
            )
            exact_keys.update(str(row[0]) for row in cur.fetchall())
    if len(exact_keys) > 1:
        raise ValueError("typed point identity maps to multiple point_map keys")
    return next(iter(exact_keys), None)


def post_fdd_run_with_busy_retry(
    http: HttpClient,
    headers: dict[str, str],
    run_body: dict[str, Any],
    *,
    request_timeout_s: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """POST /api/fdd/run; retry HTTP 409 with bounded exponential backoff."""
    attempts: list[dict[str, Any]] = []
    delay = FDD_RUN_409_BACKOFF_S
    last_status = 0
    last_raw = b""
    for attempt in range(1, FDD_RUN_409_MAX_ATTEMPTS + 1):
        status, _hdrs, raw = http.request(
            "POST",
            "/api/fdd/run",
            headers=headers,
            json_body=run_body,
            timeout=request_timeout_s,
        )
        last_status = status
        last_raw = raw
        attempts.append({"attempt": attempt, "http_status": status})
        if status == 409 and attempt < FDD_RUN_409_MAX_ATTEMPTS:
            time.sleep(delay)
            delay = min(delay * 2.0, FDD_RUN_409_BACKOFF_CAP_S)
            continue
        if not 200 <= status < 300:
            snippet = raw[:240].decode("utf-8", errors="replace")
            raise RuntimeError(f"POST /api/fdd/run -> HTTP {status}: {snippet}")
        body = json.loads(raw.decode("utf-8") or "{}")
        meta = {
            "http_attempts": attempts,
            "request_timeout_s": request_timeout_s,
            "final_http_status": status,
        }
        return body, meta
    snippet = last_raw[:240].decode("utf-8", errors="replace")
    raise RuntimeError(
        f"POST /api/fdd/run busy after {FDD_RUN_409_MAX_ATTEMPTS} attempts "
        f"(last HTTP {last_status}): {snippet}"
    )

ANALYTICS_POST_ROUTES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("/api/analytics/runtime", {}),
    ("/api/analytics/vav-health", {}),
    ("/api/analytics/ahu-health", {}),
    ("/api/analytics/ahu-temperature-health", {}),
    ("/api/analytics/ahu-pressure-health", {}),
    ("/api/analytics/ahu-economizer-health", {}),
    ("/api/analytics/chiller-health", {}),
    ("/api/analytics/cooling-tower-health", {}),
    ("/api/analytics/boiler-health", {}),
    ("/api/analytics/hp-health", {}),
    ("/api/analytics/zone-other-health", {}),
    ("/api/analytics/sensor-health", {}),
    ("/api/analytics/sensor-faults", {}),
    ("/api/analytics/pid-hunting", {}),
    ("/api/analytics/schedule", {}),
    ("/api/analytics/mechanical-cooling", {}),
    ("/api/analytics/bas-vs-web-oat", {}),
    ("/api/analytics/inspect", {}),
    ("/api/analytics/economizer", {}),
    ("/api/analytics/rcx/ahu", {}),
    ("/api/analytics/rcx/vav", {}),
    ("/api/analytics/rcx/chiller", {}),
    ("/api/analytics/rcx/boiler", {}),
    ("/api/analytics/rcx/preset", {"series": {"preset_id": "economizer_deltas"}}),
    ("/api/analytics/metering", {}),
    ("/api/analytics/mv", {}),
    ("/api/analytics/fuel", {}),
    ("/api/analytics/setpoints", {}),
    ("/api/analytics/diurnal", {}),
)

TELEMETRY_TABLES = ("sample", "point_map", "authorized_series")


def load_dotenv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        out[key] = value
        os.environ.setdefault(key, value)
    return out


def load_sites_config(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sites = doc.get("sites") if isinstance(doc, dict) else doc
    if not isinstance(sites, list) or not sites:
        raise SystemExit(f"sites config must be a non-empty list: {path}")
    for index, site in enumerate(sites):
        if not isinstance(site, dict) or not str(site.get("building_id", "")).strip():
            raise SystemExit(f"sites[{index}] needs building_id")
    return sites


def load_rule_registry() -> list[dict[str, Any]]:
    import yaml

    reg_path = REPO / "sql" / "fdd" / "registry.yaml"
    doc = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    rules = doc.get("rules") or []
    if len(rules) < 70:
        raise SystemExit(f"registry.yaml expected ~77 rules, found {len(rules)}")
    return rules


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_ip_oracle(source_root: Path) -> dict[str, Any]:
    """Load only the explicitly pinned IP oracle and report its provenance."""
    import importlib
    import yaml

    root = source_root.expanduser().resolve()
    project_file = root / "pyproject.toml"
    registry_path = root / "sql" / "fdd" / "registry.yaml"
    if not project_file.is_file() or not registry_path.is_file():
        raise SystemExit("oracle source root must contain pyproject.toml and sql/fdd/registry.yaml")
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    project_version = str(
        project.get("project", {}).get("version")
        or project.get("tool", {}).get("poetry", {}).get("version")
        or ""
    )
    if project_version != "4.4.9":
        raise SystemExit("IP oracle source must declare open-fdd version 4.4.9")
    for name in tuple(sys.modules):
        if name == "open_fdd" or name.startswith("open_fdd."):
            del sys.modules[name]
    sys.path.insert(0, str(root))
    try:
        importlib.invalidate_caches()
        package = importlib.import_module("open_fdd")
        package_path = Path(package.__file__).resolve()
        if not package_path.is_relative_to(root):
            raise SystemExit("imported open_fdd is outside the explicit oracle source root")
        version = str(getattr(package, "__version__", ""))
        if version != "4.4.9":
            raise SystemExit(f"IP oracle runtime version mismatch: expected 4.4.9, found {version!r}")
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if head != "35c17ac2d4ccc9ff677f5dd8d928e786aea0e2f0":
            raise SystemExit("IP oracle source must be pinned to registry baseline commit 35c17ac")
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--", "pyproject.toml", "open_fdd", "sql/fdd/registry.yaml"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            raise SystemExit("IP oracle package and registry files must be clean at the pinned commit")
        registry_bytes = registry_path.read_bytes()
        registry = yaml.safe_load(registry_bytes)
        rules = registry.get("rules") or []
        if len(rules) < 70:
            raise SystemExit(f"pinned IP registry expected ~77 rules, found {len(rules)}")
        registry_hash = hashlib.sha256(registry_bytes).hexdigest()
        if registry_hash != "b0397a06d834109a77e85599c81e7c81cbacfab7d38372503c943c1f26e1fcbf":
            raise SystemExit("IP registry ABI mismatch for pinned 4.4.9 baseline")
        return {
            "source_root": str(root),
            "version": version,
            "import_path": str(package_path),
            "git_head": head,
            "registry_sha256": registry_hash,
            "python_tree_sha256": _tree_sha256(root / "open_fdd"),
            "rule_count": len(rules),
            "rules": rules,
        }
    except subprocess.CalledProcessError as exc:
        raise SystemExit("oracle source root must be a git checkout with a resolvable HEAD") from exc


def require_database_url() -> str:
    url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "Timescale URL required for capture mode: set OPENFDD_DATABASE_URL or "
            "pass --database-url (host example: "
            "postgresql://openfdd:PASSWORD@127.0.0.1:5432/openfdd)"
        )
    return url


def resolve_capture_password(args: argparse.Namespace) -> str | None:
    """Login password after ``--jwt-env`` is loaded; never log or print."""
    if args.password is not None:
        return str(args.password)
    return (
        os.environ.get("OPENFDD_AGENT_PASSWORD")
        or os.environ.get("OPENFDD_STRESS_PASS")
        or os.environ.get("OPENFDD_ADMIN_PASSWORD")
    )


def _pandas_pair_status_from_result(result: Any) -> tuple[str, str] | None:
    """Map non-computed run_rule outcomes to capture pair_status.

    Returns ``None`` when ``confirmed_fault`` is present and daily seconds should
    be rolled up.
    """
    status = str(getattr(result, "status", "OK"))
    if getattr(result, "confirmed_fault", None) is not None:
        return None
    if status == "ERROR":
        return ("error", status)
    applicable = getattr(result, "applicable", True)
    if not applicable or status.startswith("SKIPPED") or status.startswith("NOT_APPLICABLE"):
        reason = "missing_roles" if "MISSING_ROLES" in status else status.lower()
        return ("not_applicable", reason)
    if status.startswith("NOT_ASSESSED"):
        return ("not_applicable", status.lower())
    return ("error", "missing confirmed_fault on result")


def db_connect():
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg is required for capture mode (Timescale SQL reads). Install with: "
            "python3 -m pip install 'psycopg[binary]' "
            "(listed in scripts/qualification/requirements.txt for stress tooling)"
        ) from exc

    return psycopg.connect(require_database_url())


def require_pandas_oracle() -> None:
    from importlib.util import find_spec

    if find_spec("open_fdd") is None or find_spec("pandas") is None:
        raise SystemExit(
            "capture requires pandas and open-fdd[oracle] unless --skip-pandas is set"
        )


def require_oracle_runtime(oracle: dict[str, Any]) -> None:
    """Ensure oracle imports used by the capture remain inside the pinned checkout."""
    from open_fdd.rules import RULES_BY_ID

    registry_ids = {str(rule.get("rule_id")) for rule in oracle["rules"] if rule.get("rule_id")}
    aliases = {"economizer-high-limit": "ECON_HL", "economizer-high-limit-fault": "ECON_HL"}
    # Registry rows without a Python implementation remain explicit in output as
    # no_pandas_function; they must not be mistaken for package/provenance errors.
    oracle["pandas_implemented_rule_ids"] = sorted(
        rid for rid in registry_ids if rid in RULES_BY_ID or aliases.get(rid) in RULES_BY_ID
    )
    oracle["no_pandas_function_rule_ids"] = sorted(
        registry_ids.difference(oracle["pandas_implemented_rule_ids"])
    )


def require_unit_inventory(point_map_count: int, rows: list[dict[str, Any]]) -> None:
    keys = [str(row.get("openfdd_key") or "") for row in rows]
    if len(keys) != point_map_count or len(set(keys)) != point_map_count or any(not key for key in keys):
        raise RuntimeError(
            f"unit inventory does not cover every point_map key: "
            f"expected={point_map_count} rows={len(keys)} unique={len(set(keys))}"
        )


def default_output_dir(shortsha: str) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    sha = shortsha.removeprefix("sha-")[:7] or "local"
    return Path(os.path.expanduser("~")) / "openfdd-si-cutover" / f"baseline-{sha}-{day}"


def baseline_capture_disqualifiers(meta: dict[str, Any]) -> list[str]:
    """Reasons a capture manifest cannot qualify as the frozen IP baseline."""
    reasons: list[str] = []
    if meta.get("skip_pandas"):
        reasons.append("skip_pandas")
    if meta.get("allow_errors"):
        reasons.append("allow_errors")
    oracle = meta.get("ip_oracle")
    if not isinstance(oracle, dict):
        reasons.append("missing_ip_oracle")
    for site in meta.get("sites") or []:
        if not isinstance(site, dict):
            continue
        for reason in site.get("disqualifying_reasons") or []:
            token = str(reason).strip()
            if token and token not in reasons:
                reasons.append(token)
    return reasons


def health_shortsha(http, headers: dict[str, str]) -> str:
    body = http.get_json("/api/version", headers=headers)
    version = str(body.get("version") or body.get("semver") or "")
    if "+" in version:
        return version.split("+", 1)[1]
    return str(body.get("shortsha") or body.get("git_sha") or "local")


def telemetry_row_counts(
    conn,
    building_id: str,
    *,
    sample_before: str | None = None,
) -> dict[str, int]:
    """Row counts for read-only guard.

    When ``sample_before`` is set (capture ``window_end``), only ``sample`` rows
    with ``ts < window_end`` are counted so live NF ingest after the window does
    not trip the guard. ``point_map`` and ``authorized_series`` are full-table
    counts (no timestamp column).
    """
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in TELEMETRY_TABLES:
            if table == "sample" and sample_before:
                cur.execute(
                    """
                    SELECT COUNT(*)::bigint FROM sample
                    WHERE site_id = %s AND ts < %s::timestamptz
                    """,
                    (building_id, sample_before),
                )
            else:
                cur.execute(
                    f"SELECT COUNT(*)::bigint FROM {table} WHERE site_id = %s",
                    (building_id,),
                )
            counts[table] = int(cur.fetchone()[0])
    return counts


def fetch_sql_daily_rows(
    conn,
    *,
    building_id: str,
    window_start: str,
    window_end: str,
) -> list[dict[str, Any]]:
    sql = """
        SELECT rule_id, equipment_id, bucket_start, fault_seconds, covered_seconds
        FROM fdd_interval_result
        WHERE site_id = %s
          AND bucket_start >= %s::timestamptz
          AND bucket_start < %s::timestamptz
        ORDER BY rule_id, equipment_id, bucket_start
    """
    daily: dict[tuple[str, str, str], dict[str, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (building_id, window_start, window_end))
        for rule_id, equipment_id, bucket_start, fault_s, covered_s in cur.fetchall():
            utc_day = bucket_start.astimezone(timezone.utc).date().isoformat()
            key = (rule_id, equipment_id, utc_day)
            slot = daily.setdefault(
                key,
                {
                    "building_id": building_id,
                    "rule_id": rule_id,
                    "equipment_id": equipment_id,
                    "utc_day": utc_day,
                    "fault_seconds": 0.0,
                    "covered_seconds": 0.0,
                    "status": "OK",
                },
            )
            slot["fault_seconds"] += float(fault_s or 0)
            slot["covered_seconds"] += float(covered_s or 0)
    return list(daily.values())


def fetch_run_status_rows(
    conn,
    *,
    building_id: str,
    run_id: str,
) -> dict[tuple[str, str], str]:
    sql = """
        SELECT rule_id, equipment_id, status
        FROM fdd_run
        WHERE site_id = %s AND detail->>'run_id' = %s
    """
    out: dict[tuple[str, str], str] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (building_id, run_id))
        for rule_id, equipment_id, status in cur.fetchall():
            out[(rule_id, equipment_id)] = str(status or "")
    return out


def no_applicable_status_rows(status_map: dict[tuple[str, str], str]) -> list[dict[str, str]]:
    """Keep persisted no-target statuses visible even when there is no equipment row."""
    out = []
    for (rule_id, equipment_id), status in sorted(status_map.items()):
        if status == "SKIP_NO_TARGETS" or status.startswith("NOT_APPLICABLE"):
            out.append(
                {
                    "rule_id": rule_id,
                    "equipment_id": equipment_id,
                    "status": status,
                    "pair_status": "not_applicable",
                }
            )
    return out


def validate_batch_scope_rule_sets(
    *,
    computed_rule_ids: set[str],
    carried_rule_ids: set[str],
    batch: set[str],
    registry_rule_ids: set[str],
) -> None:
    """Ensure a scoped registry run split matches batch vs carry-forward semantics."""
    overlap = computed_rule_ids & carried_rule_ids
    if overlap:
        raise ValueError(
            "persisted batch scope overlap between computed and carried rules: "
            + ", ".join(sorted(overlap))
        )
    if computed_rule_ids != batch:
        missing = sorted(batch - computed_rule_ids)
        extra = sorted(computed_rule_ids - batch)
        detail = []
        if missing:
            detail.append(f"missing computed={missing}")
        if extra:
            detail.append(f"unexpected computed={extra}")
        raise ValueError(
            "freshly computed rule set must equal batch"
            + (f" ({'; '.join(detail)})" if detail else "")
        )
    all_persisted = computed_rule_ids | carried_rule_ids
    if carried_rule_ids or len(all_persisted) == len(registry_rule_ids):
        expected_carried = registry_rule_ids - batch
        if carried_rule_ids != expected_carried:
            missing = sorted(expected_carried - carried_rule_ids)
            extra = sorted(carried_rule_ids - expected_carried)
            detail = []
            if missing:
                detail.append(f"missing carried={missing}")
            if extra:
                detail.append(f"unexpected carried={extra}")
            raise ValueError(
                "carried-forward rule set must equal registry minus batch"
                + (f" ({'; '.join(detail)})" if detail else "")
            )
    elif carried_rule_ids:
        raise ValueError(
            "unexpected carried-forward rows without a full registry cohort"
        )


def fetch_batch_run_rule_sets(
    conn, *, building_id: str, run_id: str, batch: set[str]
) -> tuple[set[str], set[str]]:
    """Split persisted rows for one logical run into batch-computed vs parent carry-forward.

    Partial registry runs copy untouched rules from the parent generation under the new
    ``detail->>'run_id'`` (``fdd_registry_persist::copy_parent_runs`` stamps
    ``detail.generation.parent_run_id``). Freshly evaluated rules belong to ``batch``.
    """
    computed: set[str] = set()
    carried: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rule_id,
                   bool_and(detail->'generation'->>'parent_run_id' IS NOT NULL) AS has_parent
            FROM fdd_run
            WHERE site_id = %s AND detail->>'run_id' = %s
            GROUP BY rule_id
            """,
            (building_id, run_id),
        )
        rows = cur.fetchall()
    for rule_id, has_parent in rows:
        rid = str(rule_id)
        if rid in batch:
            computed.add(rid)
        else:
            if batch and not has_parent:
                raise RuntimeError(
                    f"carried-forward rule {rid} missing detail.generation.parent_run_id"
                )
            carried.add(rid)
    return computed, carried


def fetch_computed_run_window_bounds(
    conn, *, building_id: str, run_id: str, batch: set[str]
) -> tuple[Any, Any, Any, Any] | None:
    """Window bounds for rows this batch evaluated (ignore carry-forward copies)."""
    if not batch:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MIN(window_start), MAX(window_start), MIN(window_end), MAX(window_end)
            FROM fdd_run
            WHERE site_id = %s AND detail->>'run_id' = %s AND rule_id = ANY(%s::text[])
            """,
            (building_id, run_id, list(batch)),
        )
        start_min, start_max, end_min, end_max = cur.fetchone()
    return (
        (start_min, start_max, end_min, end_max) if start_min is not None else None
    )


def validate_batch_persisted_scope(
    conn,
    *,
    building_id: str,
    run_id: str,
    batch: set[str],
    registry_rule_ids: set[str],
) -> tuple[Any, Any, Any, Any]:
    """Validate scoped persist semantics and return computed-row window bounds."""
    computed, carried = fetch_batch_run_rule_sets(
        conn, building_id=building_id, run_id=run_id, batch=batch
    )
    try:
        validate_batch_scope_rule_sets(
            computed_rule_ids=computed,
            carried_rule_ids=carried,
            batch=batch,
            registry_rule_ids=registry_rule_ids,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    bounds = fetch_computed_run_window_bounds(
        conn, building_id=building_id, run_id=run_id, batch=batch
    )
    if bounds is None:
        raise RuntimeError("batch persisted no computed window bounds")
    return bounds


def fdd_run_created_at_marker(conn, building_id: str) -> datetime:
    """Latest ``fdd_run.created_at`` for a site (UTC)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(created_at), TIMESTAMPTZ '1970-01-01 00:00:00+00')
            FROM fdd_run WHERE site_id = %s
            """,
            (building_id,),
        )
        marker = cur.fetchone()[0]
    if isinstance(marker, datetime):
        if marker.tzinfo is None:
            marker = marker.replace(tzinfo=timezone.utc)
        return marker.astimezone(timezone.utc)
    return datetime.fromisoformat(str(marker).replace("Z", "+00:00")).astimezone(timezone.utc)


def interleaved_logical_run_ids(
    conn,
    *,
    building_id: str,
    after: datetime,
    allowed_run_ids: set[str],
) -> list[str]:
    """Logical run ids written after ``after`` that are not part of this capture."""
    allowed = sorted(allowed_run_ids)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT detail->>'run_id' AS logical_run_id
            FROM fdd_run
            WHERE site_id = %s
              AND created_at > %s
              AND detail->>'run_id' IS NOT NULL
              AND NOT (detail->>'run_id' = ANY(%s::text[]))
            ORDER BY logical_run_id
            """,
            (building_id, after, allowed),
        )
        return [str(row[0]) for row in cur.fetchall() if row[0]]


def assert_no_interleaved_fdd_run(
    conn,
    *,
    building_id: str,
    marker: datetime,
    allowed_run_ids: set[str],
) -> None:
    """Fail closed when AFDD or another writer publishes a new generation mid-capture."""
    foreign = interleaved_logical_run_ids(
        conn,
        building_id=building_id,
        after=marker,
        allowed_run_ids=allowed_run_ids,
    )
    if foreign:
        raise CaptureQualificationError(
            f"concurrent_non_capture_fdd_run:{foreign[0]}"
        )


def fetch_run_scope(
    conn, *, building_id: str, run_id: str
) -> tuple[set[str], tuple[Any, Any, Any, Any] | None]:
    """Read persisted rule/window scope so a successful HTTP response cannot mask omission."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT array_agg(DISTINCT rule_id), MIN(window_start), MAX(window_start),
                      MIN(window_end), MAX(window_end)
               FROM fdd_run WHERE site_id = %s AND detail->>'run_id' = %s""",
            (building_id, run_id),
        )
        rule_ids, start_min, start_max, end_min, end_max = cur.fetchone()
    return {str(rule_id) for rule_id in (rule_ids or [])}, (
        start_min, start_max, end_min, end_max
    ) if start_min is not None else None


def parse_utc_instant(value: str | datetime) -> datetime:
    """Parse an API/DB timestamp and normalize it to UTC for instant comparisons."""
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def effective_run_window(
    run_resp: dict[str, Any], *, requested_start: str | None, requested_end: str | None
) -> tuple[str, str]:
    """Read effective sample-clamped bounds from the run manifest or direct fields."""
    manifest_window = run_resp.get("window") if isinstance(run_resp.get("window"), dict) else {}
    start = str(run_resp.get("window_start") or manifest_window.get("start") or requested_start or "")
    end = str(run_resp.get("window_end") or manifest_window.get("end") or requested_end or "")
    if not start or not end:
        raise ValueError("FDD run returned no effective window bounds")
    start_instant = parse_utc_instant(start)
    end_instant = parse_utc_instant(end)
    if start_instant >= end_instant:
        raise ValueError("FDD run returned an empty or reversed effective window")
    if requested_start and start_instant < parse_utc_instant(requested_start):
        raise ValueError("FDD effective window starts before the requested window")
    if requested_end and end_instant > parse_utc_instant(requested_end):
        raise ValueError("FDD effective window ends after the requested window")
    return start, end


def require_same_batch_window(
    candidate_start: str, candidate_end: str, frozen_start: str, frozen_end: str
) -> None:
    """Keep every rule batch on the first batch's effective half-open window."""
    if (
        parse_utc_instant(candidate_start) != parse_utc_instant(frozen_start)
        or parse_utc_instant(candidate_end) != parse_utc_instant(frozen_end)
    ):
        raise ValueError("rule batch changed the frozen effective window")


def write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Durably publish a unique receipt file without exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def merge_status(
    daily_rows: list[dict[str, Any]], status_map: dict[tuple[str, str], str]
) -> None:
    for row in daily_rows:
        key = (row["rule_id"], row["equipment_id"])
        row["status"] = status_map.get(key, row.get("status", "OK"))


def build_rule_batches(rules: list[dict[str, Any]], batch_size: int) -> list[list[str]]:
    """Partition the ordered registry IDs without changing the requested window."""
    rule_ids = [str(rule.get("rule_id") or "").strip() for rule in rules]
    rule_ids = [rule_id for rule_id in rule_ids if rule_id]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("registry contains duplicate rule IDs")
    width = batch_size if batch_size > 0 else max(1, len(rule_ids))
    batches = [rule_ids[index : index + width] for index in range(0, len(rule_ids), width)]
    flattened = [rule_id for batch in batches for rule_id in batch]
    if flattened != rule_ids:
        raise ValueError("rule batches do not cover registry IDs exactly once in order")
    return batches


def resolve_w2c_source_unit(
    *,
    overlay_unit: str | None,
    tag_unit: str | None,
    column_unit: str | None,
    package_unit_system: str | None,
) -> str:
    for candidate in (overlay_unit, tag_unit, column_unit, package_unit_system):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return "unresolved"


def unit_inventory_rows(
    http,
    headers: dict[str, str],
    conn,
    *,
    building_id: str,
) -> tuple[list[dict[str, Any]], int]:
    mapping = http.get_json(
        "/api/csv/import/package/mapping",
        headers=headers,
        params={"building_id": building_id},
    )
    package_unit_system = ""
    session = mapping.get("session_config") if isinstance(mapping, dict) else {}
    if isinstance(session, dict):
        package_unit_system = str(session.get("unit_system") or "")
    mapping_column_units: dict[tuple[str, str], set[str]] = {}
    equipment_rows = mapping.get("equipment") if isinstance(mapping, dict) else []
    for equipment in equipment_rows if isinstance(equipment_rows, list) else []:
        if not isinstance(equipment, dict):
            continue
        equipment_id = str(equipment.get("equipment_id") or "").strip()
        columns = equipment.get("columns")
        for column in columns if isinstance(columns, list) else []:
            if not isinstance(column, dict):
                continue
            role = str(column.get("role") or column.get("fdd_role") or "").strip()
            unit = str(column.get("unit") or column.get("column_unit") or column.get("csv_unit") or "").strip()
            if equipment_id and role and unit:
                mapping_column_units.setdefault((equipment_id, role), set()).add(unit)
    typed_units_by_key: dict[str, set[str]] = {}
    typed_points = post_sparql(
        http,
        headers,
        building_id=building_id,
        query_id="fdd_role_candidates",
    )
    for point in typed_points:
        if not isinstance(point, dict):
            continue
        equipment_id = _sparql_equipment_id(point)
        unit = str(point.get("unit") or "").strip()
        if not equipment_id or not unit:
            continue
        key = resolve_bound_openfdd_key(
            conn, site_id=building_id, equipment_id=equipment_id, point=point
        )
        if key:
            typed_units_by_key.setdefault(key, set()).add(unit)
    sample_metadata: dict[str, dict[str, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT openfdd_key,
                   array_agg(DISTINCT unit) FILTER (WHERE unit IS NOT NULL AND unit <> '') AS units,
                   COUNT(*)::bigint AS sample_count,
                   MIN(ts) AS first_sample_at,
                   MAX(ts) AS last_sample_at
            FROM sample
            WHERE site_id = %s
            GROUP BY openfdd_key
            """,
            (building_id,),
        )
        for key, units, sample_count, first_at, last_at in cur.fetchall():
            if key:
                sample_metadata[str(key)] = {
                    "units": sorted({str(unit) for unit in (units or []) if unit}),
                    "sample_count": int(sample_count or 0),
                    "first_sample_at": first_at.isoformat() if first_at else "",
                    "last_sample_at": last_at.isoformat() if last_at else "",
                }
    with conn.cursor() as cur:
        cur.execute(
            """SELECT equipment_id, role, openfdd_key,
                      to_jsonb(point_map)->>'unit' AS unit,
                      to_jsonb(point_map)->>'source_unit' AS source_unit
               FROM point_map WHERE site_id = %s
               ORDER BY equipment_id, role, openfdd_key""",
            (building_id,),
        )
        point_rows = cur.fetchall()
    rows: list[dict[str, Any]] = []
    unresolved = 0
    for equipment_value, role_value, key_value, unit_value, source_unit_value in point_rows:
        equipment_id = str(equipment_value or "").strip()
        role = str(role_value or "").strip()
        openfdd_key = str(key_value or "").strip()
        if not openfdd_key:
            continue
        point_map_unit = str(unit_value or "").strip()
        declared_source_unit = str(source_unit_value or "").strip()
        column_units = set(mapping_column_units.get((equipment_id, role), set()))
        sparql_units = typed_units_by_key.get(openfdd_key, set())
        column_units.update(sparql_units)
        column_unit = next(iter(column_units)) if len(column_units) == 1 else None
        resolved = resolve_w2c_source_unit(
            overlay_unit=point_map_unit or None,
            tag_unit=declared_source_unit or None,
            column_unit=column_unit,
            package_unit_system=package_unit_system or None,
        )
        if resolved == "unresolved":
            unresolved += 1
        sample_meta = sample_metadata.get(openfdd_key, {})
        sample_unit_values = sample_meta.get("units", [])
        storage_units = {unit for unit in [point_map_unit, *sample_unit_values] if unit}
        inventory_status = "ok" if role else "no_role"
        rows.append(
            {
                "building_id": building_id,
                "openfdd_key": openfdd_key,
                "role": role,
                "inventory_status": inventory_status,
                "point_map_unit": point_map_unit,
                "sample_unit": sample_unit_values[0] if len(sample_unit_values) == 1 else "",
                "sample_unit_values": sample_unit_values,
                "sparql_unit_values": sorted(sparql_units),
                "sample_count": sample_meta.get("sample_count", 0),
                "first_sample_at": sample_meta.get("first_sample_at", ""),
                "last_sample_at": sample_meta.get("last_sample_at", ""),
                "package_unit_system": package_unit_system,
                "w2c_source_unit": resolved,
                "declared_source_unit": declared_source_unit,
                "storage_source_unit_conflict": bool(
                    (declared_source_unit and any(unit != declared_source_unit for unit in storage_units))
                    or (not declared_source_unit and resolved != "unresolved" and any(unit != resolved for unit in storage_units))
                ),
                "ambiguous_sample_units": len(sample_unit_values) > 1,
                "ambiguous_column_units": len(column_units) > 1,
                "ambiguous_sparql_units": len(sparql_units) > 1,
            }
        )
    return rows, unresolved


def analytics_rows_for_site(
    http,
    headers: dict[str, str],
    *,
    building_id: str,
    window_start: str | None,
    window_end: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, extra in ANALYTICS_POST_ROUTES:
        payload: dict[str, Any] = {"building_id": building_id, "refresh": True}
        if window_start:
            payload["window_start"] = window_start
        if window_end:
            payload["window_end"] = window_end
        payload.update(extra)
        try:
            body = analytics_post(http, headers, path, payload)
        except RuntimeError as exc:
            out.append(
                {
                    "building_id": building_id,
                    "endpoint": path,
                    "row": {"error": str(exc), "ok": False},
                }
            )
            continue
        envelope = body.get("analytics") if isinstance(body.get("analytics"), dict) else body
        rows: list[Any] = []
        if isinstance(envelope, dict):
            for key in ("rows", "points", "equipment", "series", "data"):
                val = envelope.get(key)
                if isinstance(val, list):
                    rows = val
                    break
        if not rows and isinstance(envelope, dict) and envelope:
            rows = [envelope]
        if not rows:
            rows = [{"note": "empty", "ok": body.get("ok")}]
        for row in rows:
            if isinstance(row, dict):
                out.append({"building_id": building_id, "endpoint": path, "row": row})
    return out


def analytics_error_messages(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        payload = row.get("row")
        if not isinstance(payload, dict):
            continue
        message = payload.get("error")
        if message or payload.get("ok") is False:
            errors.append(f"{row['endpoint']}: {message or 'ok=false'}")
    return errors


def rule_params_from_registry(rule: dict[str, Any]) -> dict[str, float]:
    params: dict[str, float] = {}
    for name, spec in (rule.get("parameters") or {}).items():
        if not isinstance(spec, dict) or "default" not in spec:
            continue
        try:
            params[name] = float(spec["default"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"rule {rule.get('rule_id')}: bad default for parameter {name!r}: {exc}"
            ) from exc
    return params


def daily_fault_and_covered_seconds(
    confirmed_mask,
    sample_index,
    *,
    poll_seconds: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Eligible-hold seconds per UTC day — mirrors ``open_fdd.rules.base.hours_true``.

    SQL ``fdd_interval_result`` fault/covered seconds come from the product FDD
    bucket writer (``services/central/src/fdd_registry_persist.rs`` distributes
    run totals into UTC-hour buckets). The pandas oracle uses the same eligible
    forward-hold semantics as ``hours_true`` for fault hours; we convert to
    seconds and roll up to UTC calendar days for P0 comparison.
    """
    import pandas as pd
    from open_fdd.rules.base import _eligible_hold_seconds

    confirmed = confirmed_mask.reindex(sample_index).fillna(False).astype(bool)
    all_true = pd.Series(True, index=sample_index)
    fault_days: dict[str, float] = {}
    covered_days: dict[str, float] = {}
    if not isinstance(sample_index, pd.DatetimeIndex):
        from open_fdd.rules.base import hours_true

        fault_days[""] = hours_true(confirmed, poll_seconds) * 3600.0
        covered_days[""] = hours_true(all_true, poll_seconds) * 3600.0
        return fault_days, covered_days
    held = _eligible_hold_seconds(sample_index)
    if held is None:
        from open_fdd.rules.base import hours_true

        fault_days[""] = hours_true(confirmed, poll_seconds) * 3600.0
        covered_days[""] = hours_true(all_true, poll_seconds) * 3600.0
        return fault_days, covered_days
    utc_index = sample_index.tz_convert("UTC")
    for i, ts in enumerate(utc_index):
        seconds = float(held.iloc[i])
        if seconds <= 0.0:
            continue
        day_key = ts.date().isoformat()
        covered_days[day_key] = covered_days.get(day_key, 0.0) + seconds
        if bool(confirmed.iloc[i]):
            fault_days[day_key] = fault_days.get(day_key, 0.0) + seconds
    return fault_days, covered_days


def equipment_frame_from_db(
    conn,
    http,
    headers,
    *,
    building_id: str,
    equipment_id: str,
    window_start: str,
    window_end: str,
    equipment_type: str = "",
) -> tuple[Any, dict[str, int]]:
    import pandas as pd

    role_map = load_role_id_to_haystack()
    skip_counts = Counter(
        {
            "skipped_other_equipment": 0,
            "skipped_unbound_no_column": 0,
            "skipped_no_role": 0,
            "skipped_unmapped_role": 0,
            "skipped_unmapped_point": 0,
        }
    )
    pts = post_sparql(
        http,
        headers,
        building_id=building_id,
        query_id="fdd_role_candidates",
        equipment_id=equipment_id,
    )
    series: dict[str, pd.Series] = {}
    for pt in pts:
        if not isinstance(pt, dict):
            continue
        row_eid = _sparql_equipment_id(pt)
        if row_eid and row_eid != equipment_id:
            skip_counts["skipped_other_equipment"] += 1
            continue
        point_id = str(pt.get("pointId") or pt.get("point_id") or "").strip()
        col = str(pt.get("column") or point_id).strip()
        role_raw = str(pt.get("fddSelection") or pt.get("canonicalRole") or "").strip()
        if not role_raw:
            skip_counts["skipped_no_role"] += 1
            continue
        haystack_col = resolve_haystack_column(role_raw, role_map)
        if haystack_col is None:
            skip_counts["skipped_unmapped_role"] += 1
            continue
        openfdd_key = resolve_bound_openfdd_key(
            conn, site_id=building_id, equipment_id=equipment_id, point=pt
        )
        if openfdd_key is None:
            if not point_id:
                skip_counts["skipped_unbound_no_column"] += 1
            else:
                skip_counts["skipped_unmapped_point"] += 1
            continue
        samples = load_samples_in_window(
            conn,
            site_id=building_id,
            openfdd_key=openfdd_key,
            window_start=window_start,
            window_end=window_end,
        )
        if not samples:
            continue
        idx = pd.to_datetime([ts for ts, _ in samples], utc=True)
        vals = [val for _, val in samples]
        if haystack_col in series:
            raise ValueError(
                f"multiple point_map identities bind to role {haystack_col} for equipment {equipment_id}"
            )
        series[haystack_col] = pd.Series(vals, index=idx, name=haystack_col)
    if not series:
        raise frame_builder_empty_error(equipment_id, skip_counts=dict(skip_counts))
    df = pd.DataFrame(series).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.attrs.update(
        equipment_id=equipment_id,
        building_id=building_id,
        unit_system="imperial",
    )
    etype = str(equipment_type or "").strip()
    if etype:
        df.attrs["equipment_type"] = etype
        df.attrs["equipType"] = etype
    return df, dict(skip_counts)


def _pair_base(building_id: str, rule_id: str, equipment_id: str) -> dict[str, Any]:
    return {
        "building_id": building_id,
        "rule_id": rule_id,
        "equipment_id": equipment_id,
        "utc_day": "",
        "fault_seconds": 0.0,
        "covered_seconds": 0.0,
        "status": "",
        "pair_status": "",
        "reason": "",
    }


def collect_pandas_fdd_rows(
    http,
    headers: dict[str, str],
    conn,
    *,
    building_id: str,
    rules: list[dict[str, Any]],
    window_start: str,
    window_end: str,
    pandas_max_rules: int | None,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    from open_fdd.analytics.units import stamp_display_units
    from open_fdd.rules import RULES_BY_ID, run_rule

    import pandas as pd

    equipment_body = http.get_json(
        "/api/fdd/equipment",
        headers=headers,
        params={"building_id": building_id},
    )
    equipment = equipment_body.get("equipment") or equipment_body.get("items") or []
    if not isinstance(equipment, list):
        equipment = []

    if pandas_max_rules is not None:
        rules_iter = rules[:pandas_max_rules]
    else:
        rules_iter = rules

    out: list[dict[str, Any]] = []
    coverage: Counter[str] = Counter()
    error_messages: list[str] = []
    frame_skip_totals: Counter[str] = Counter()
    role_map = load_role_id_to_haystack()
    frame_cache: dict[tuple[str, str, str, str], Any] = {}

    for rule in rules_iter:
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            continue
        kinds = rule.get("equipment_kinds") or []
        for equip in equipment:
            if not isinstance(equip, dict):
                continue
            eid = str(equip.get("equipment_id") or equip.get("id") or "").strip()
            etype = str(equip.get("equip_type") or equip.get("equipment_type") or "").strip()
            if not eid:
                continue
            base = _pair_base(building_id, rule_id, eid)
            if kinds and etype and etype not in kinds:
                out.append(
                    {
                        **base,
                        "pair_status": "not_applicable",
                        "reason": "equipment_type",
                    }
                )
                coverage["not_applicable"] += 1
                continue
            if rule_id not in RULES_BY_ID:
                out.append(
                    {
                        **base,
                        "pair_status": "no_pandas_function",
                        "reason": "rule absent from pinned Python oracle",
                    }
                )
                coverage["no_pandas_function"] += 1
                continue
            unmapped_required = missing_required_roles_unmapped(rule, role_map=role_map)
            if unmapped_required:
                out.append(
                    {
                        **base,
                        "pair_status": "unmapped_role",
                        "reason": ", ".join(unmapped_required),
                    }
                )
                coverage["unmapped_role"] += 1
                continue
            try:
                params = rule_params_from_registry(rule)
                frame_key = (eid, window_start, window_end, etype)
                if frame_key not in frame_cache:
                    built_frame, skip_counts = equipment_frame_from_db(
                        conn,
                        http,
                        headers,
                        building_id=building_id,
                        equipment_id=eid,
                        window_start=window_start,
                        window_end=window_end,
                        equipment_type=etype,
                    )
                    frame_cache[frame_key] = built_frame
                    frame_skip_totals.update(skip_counts)
                frame = frame_cache[frame_key].copy(deep=True)
            except UnmappedRoleError as exc:
                frame_skip_totals.update(exc.skip_counts)
                roles = ", ".join(exc.roles)
                out.append(
                    {
                        **base,
                        "pair_status": "unmapped_role",
                        "reason": roles,
                    }
                )
                coverage["unmapped_role"] += 1
                continue
            except Exception as exc:
                msg = f"{rule_id}/{eid}: {exc}"
                error_messages.append(msg)
                extra_skips = getattr(exc, "skip_counts", None)
                if isinstance(extra_skips, dict):
                    frame_skip_totals.update(extra_skips)
                out.append({**base, "pair_status": "error", "reason": str(exc)})
                coverage["error"] += 1
                continue
            stamp_display_units(frame, {"unit_system": "imperial"})
            start = pd.Timestamp(window_start, tz="UTC")
            end = pd.Timestamp(window_end, tz="UTC")
            frame = frame.loc[(frame.index >= start) & (frame.index < end)]
            if frame.empty:
                out.append(
                    {
                        **base,
                        "pair_status": "not_applicable",
                        "reason": "empty_window",
                    }
                )
                coverage["not_applicable"] += 1
                continue
            try:
                result = run_rule(
                    rule_id,
                    frame,
                    params=params,
                    poll_seconds=POLL_SECONDS,
                    require_operational_gates=True,
                )
            except Exception as exc:
                msg = f"{rule_id}/{eid}: run_rule: {exc}"
                error_messages.append(msg)
                out.append({**base, "pair_status": "error", "reason": str(exc)})
                coverage["error"] += 1
                continue
            mapped = _pandas_pair_status_from_result(result)
            if mapped is not None:
                pair_status, reason = mapped
                out.append(
                    {
                        **base,
                        "pair_status": pair_status,
                        "reason": reason,
                        "status": str(getattr(result, "status", "")),
                    }
                )
                coverage[pair_status] += 1
                if pair_status == "error":
                    error_messages.append(f"{rule_id}/{eid}: {reason}")
                continue
            confirmed = result.confirmed_fault
            status = str(getattr(result, "status", "OK"))
            fault_by_day, covered_by_day = daily_fault_and_covered_seconds(
                confirmed, frame.index, poll_seconds=POLL_SECONDS
            )
            days = sorted(set(fault_by_day) | set(covered_by_day))
            if not days:
                out.append(
                    {
                        **base,
                        "pair_status": "computed",
                        "reason": "",
                        "status": status,
                    }
                )
            else:
                for day in days:
                    out.append(
                        {
                            **base,
                            "utc_day": day,
                            "fault_seconds": fault_by_day.get(day, 0.0),
                            "covered_seconds": covered_by_day.get(day, 0.0),
                            "pair_status": "computed",
                            "reason": "",
                            "status": status,
                        }
                    )
            coverage["computed"] += 1
    return out, dict(coverage), error_messages, dict(frame_skip_totals)


def capture_site(
    http,
    headers: dict[str, str],
    conn,
    *,
    site: dict[str, Any],
    out_dir: Path,
    rules: list[dict[str, Any]],
    skip_pandas: bool,
    pandas_max_rules: int | None,
    rule_batch_size: int = 0,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> dict[str, Any]:
    building_id = str(site["building_id"]).strip()
    window_start = str(site.get("window_start") or site.get("start") or "").strip() or None
    window_end = str(site.get("window_end") or site.get("end") or "").strip() or None

    counts_before = telemetry_row_counts(
        conn, building_id, sample_before=window_end
    )

    rule_batches = build_rule_batches(rules, rule_batch_size)
    registry_rule_ids = {
        str(rule.get("rule_id") or "").strip()
        for rule in rules
        if str(rule.get("rule_id") or "").strip()
    }
    run_records: list[dict[str, Any]] = []
    fdd_run_http: list[dict[str, Any]] = []
    ws = window_start or ""
    we = window_end or ""
    receipt_id = uuid.uuid4().hex
    receipt_dir = out_dir / building_id / "run_receipts" / receipt_id
    for batch_index, batch in enumerate(rule_batches):
        batch_set = set(batch)
        allowed_run_ids = {str(record["run_id"]) for record in run_records if record.get("run_id")}
        scope_marker = fdd_run_created_at_marker(conn, building_id)
        assert_no_interleaved_fdd_run(
            conn,
            building_id=building_id,
            marker=scope_marker,
            allowed_run_ids=allowed_run_ids,
        )
        run_body: dict[str, Any] = {
            "mode": "registry",
            "building_id": building_id,
            "force_new_data": True,
            "rule_ids": batch,
        }
        if ws or window_start:
            run_body["window_start"] = ws or window_start
        if we or window_end:
            run_body["window_end"] = we or window_end
        run_resp, http_meta = post_fdd_run_with_busy_retry(
            http, headers, run_body, request_timeout_s=request_timeout_s
        )
        fdd_run_http.append({"batch_index": batch_index, **http_meta})
        if not run_resp.get("ok", True) and run_resp.get("error"):
            raise RuntimeError(f"/api/fdd/run batch {batch_index} failed: {run_resp.get('error')}")
        run_id = str(run_resp.get("run_id") or "")
        try:
            batch_ws, batch_we = effective_run_window(
                run_resp, requested_start=window_start, requested_end=window_end
            )
        except ValueError as exc:
            raise RuntimeError(f"/api/fdd/run batch {batch_index}: {exc}") from exc
        if batch_index > 0:
            try:
                require_same_batch_window(batch_ws, batch_we, ws, we)
            except ValueError as exc:
                raise RuntimeError(f"/api/fdd/run batch {batch_index}: {exc}") from exc
        ws, we = batch_ws, batch_we
        echoed_ids = run_resp.get("rule_ids")
        if echoed_ids is not None and set(map(str, echoed_ids)) != set(batch):
            raise RuntimeError(f"/api/fdd/run batch {batch_index} returned unexpected rule scope")
        if not run_id:
            raise RuntimeError(f"/api/fdd/run batch {batch_index} returned no run_id")
        receipt_path = receipt_dir / f"batch-{batch_index:04d}.json"
        run_record = {
            "capture_id": receipt_id,
            "building_id": building_id,
            "batch_index": batch_index,
            "batch_count": len(rule_batches),
            "rule_ids": batch,
            "run_id": run_id,
            "requested_window_start": window_start,
            "requested_window_end": window_end,
            "window_start": ws,
            "window_end": we,
            "window_contract": "effective half-open window must stay within request and remain frozen across batches",
            "run_status": run_resp.get("run_status", ""),
            "rules_run": run_resp.get("rules_run"),
            "receipt_path": str(receipt_path),
        }
        # This is published before validation or the next batch so an interrupted
        # capture never loses the API run ID. Receipts are append-only per capture.
        write_atomic_json(receipt_path, run_record)
        allowed_run_ids.add(run_id)
        assert_no_interleaved_fdd_run(
            conn,
            building_id=building_id,
            marker=scope_marker,
            allowed_run_ids=allowed_run_ids,
        )
        try:
            persisted_bounds = validate_batch_persisted_scope(
                conn,
                building_id=building_id,
                run_id=run_id,
                batch=batch_set,
                registry_rule_ids=registry_rule_ids,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"/api/fdd/run batch {batch_index}: {exc}") from exc
        computed_rule_ids = batch_set
        if (
            persisted_bounds is None
            or parse_utc_instant(persisted_bounds[0])
            != parse_utc_instant(persisted_bounds[1])
            or parse_utc_instant(persisted_bounds[2])
            != parse_utc_instant(persisted_bounds[3])
        ):
            raise RuntimeError(f"/api/fdd/run batch {batch_index} persisted inconsistent window bounds")
        if (
            parse_utc_instant(persisted_bounds[0]) != parse_utc_instant(batch_ws)
            or parse_utc_instant(persisted_bounds[2]) != parse_utc_instant(batch_we)
        ):
            raise RuntimeError(f"/api/fdd/run batch {batch_index} persisted a different window")
        run_record["persisted_rule_ids"] = sorted(computed_rule_ids | (registry_rule_ids - batch_set))
        run_record["computed_rule_ids"] = sorted(computed_rule_ids)
        run_record["carried_rule_ids"] = sorted(registry_rule_ids - batch_set)
        run_record["persisted_window_start"] = persisted_bounds[0].isoformat()
        run_record["persisted_window_end"] = persisted_bounds[2].isoformat()
        batch_status = fetch_run_status_rows(
            conn, building_id=building_id, run_id=run_id
        )
        run_record["no_applicable_rows"] = no_applicable_status_rows(
            {
                key: status
                for key, status in batch_status.items()
                if key[0] in batch_set
            }
        )
        write_atomic_json(receipt_path, run_record)
        run_records.append(run_record)
    if not ws or not we:
        raise RuntimeError("FDD run returned no window_start/window_end")

    assert_no_interleaved_fdd_run(
        conn,
        building_id=building_id,
        marker=scope_marker,
        allowed_run_ids={str(record["run_id"]) for record in run_records if record.get("run_id")},
    )

    sql_daily = fetch_sql_daily_rows(
        conn, building_id=building_id, window_start=ws, window_end=we
    )
    for run_record in run_records:
        batch_rules = set(run_record["rule_ids"])
        status_map = fetch_run_status_rows(
            conn, building_id=building_id, run_id=run_record["run_id"]
        )
        merge_status(
            sql_daily,
            {key: value for key, value in status_map.items() if key[0] in batch_rules},
        )

    analytics = analytics_rows_for_site(
        http, headers, building_id=building_id, window_start=ws, window_end=we
    )
    analytics_errors = analytics_error_messages(analytics)
    units, unresolved_units = unit_inventory_rows(
        http, headers, conn, building_id=building_id
    )
    require_unit_inventory(counts_before.get("point_map", 0), units)

    pandas_rows: list[dict[str, Any]] = []
    pandas_coverage: dict[str, int] = {}
    pandas_errors: list[str] = []
    pandas_frame_skips: dict[str, int] = {}
    if skip_pandas:
        pandas_coverage = {"skipped": 1}
    else:
        pandas_rows, pandas_coverage, pandas_errors, pandas_frame_skips = collect_pandas_fdd_rows(
            http,
            headers,
            conn,
            building_id=building_id,
            rules=rules,
            window_start=ws,
            window_end=we,
            pandas_max_rules=pandas_max_rules,
        )

    # The unchanged-telemetry guard must compare the same snapshot boundary on
    # both reads; the API's effective sample-clamped end may precede the request.
    counts_after = telemetry_row_counts(conn, building_id, sample_before=window_end)
    sample_counts = [
        {"building_id": building_id, "table": table, "row_count": counts_after[table]}
        for table in TELEMETRY_TABLES
    ]
    if counts_before != counts_after:
        raise RuntimeError(
            f"telemetry row counts changed for {building_id}: "
            f"before={counts_before} after={counts_after}"
        )

    site_dir = out_dir / building_id
    site_dir.mkdir(parents=True, exist_ok=True)
    with JsonlGzWriter(site_dir / "sql_fdd_daily.jsonl.gz") as writer:
        for row in sql_daily:
            writer.write(row)
    with JsonlGzWriter(site_dir / "analytics_rows.jsonl.gz") as writer:
        for row in analytics:
            writer.write(row)
    with JsonlGzWriter(site_dir / "pandas_fdd_daily.jsonl.gz") as writer:
        for row in pandas_rows:
            writer.write(row)
    with JsonlGzWriter(site_dir / "unit_inventory.jsonl.gz") as writer:
        for row in units:
            writer.write(row)
    with JsonlGzWriter(site_dir / "sample_counts.jsonl.gz") as writer:
        for row in sample_counts:
            writer.write(row)
    persisted = [
        {
            "building_id": building_id,
            "run_id": run_records[-1]["run_id"] if run_records else "",
            "run_records": run_records,
            "window_start": ws,
            "window_end": we,
            "fdd_run_http": fdd_run_http,
        }
    ]
    with JsonlGzWriter(site_dir / "persisted_runs.jsonl.gz") as writer:
        for row in persisted:
            writer.write(row)

    return {
        "building_id": building_id,
        "window_start": ws,
        "window_end": we,
        "run_id": run_records[-1]["run_id"] if run_records else "",
        "run_records": run_records,
        "sql_rows": len(sql_daily),
        "analytics_rows": len(analytics),
        "pandas_rows": len(pandas_rows),
        "unit_rows": len(units),
        "unresolved_units": unresolved_units,
        "pandas_coverage": pandas_coverage,
        "pandas_frame_skips": pandas_frame_skips,
        "pandas_errors": pandas_errors,
        "analytics_errors": analytics_errors,
        "fdd_run_http": fdd_run_http,
    }


def emit_ip_goldens(
    out_dir: Path,
    *,
    golden_dir: Path,
    site_summaries: list[dict[str, Any]],
) -> None:
    golden_dir.mkdir(parents=True, exist_ok=True)
    for summary in site_summaries:
        building_id = summary["building_id"]
        site_dir = out_dir / building_id
        golden: dict[str, Any] = {"building_id": building_id, "schema": "si-cutover-ip-golden-v1"}
        for name in (
            "sql_fdd_daily.jsonl.gz",
            "analytics_rows.jsonl.gz",
            "pandas_fdd_daily.jsonl.gz",
        ):
            path = site_dir / name
            if not path.is_file():
                continue
            import gzip

            rows = []
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
            golden[name.removesuffix(".jsonl.gz")] = rows
        out_path = golden_dir / f"{building_id}.json"
        out_path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_self_test() -> int:
    records = {
        "sql_fdd_daily": [
            {
                "building_id": "SYNTH_SELFTEST",
                "rule_id": "FC1",
                "equipment_id": "AHU_1",
                "utc_day": "2026-06-01",
                "fault_seconds": 120.0,
                "covered_seconds": 3600.0,
                "status": "FAULT",
            }
        ],
        "analytics_rows": [
            {
                "building_id": "SYNTH_SELFTEST",
                "endpoint": "/api/analytics/economizer",
                "row": {"ok": True},
            }
        ],
        "pandas_fdd_daily": [
            {
                "building_id": "SYNTH_SELFTEST",
                "rule_id": "FC1",
                "equipment_id": "AHU_1",
                "utc_day": "2026-06-01",
                "fault_seconds": 120.0,
                "covered_seconds": 3600.0,
                "status": "FAULT",
                "pair_status": "computed",
                "reason": "",
            }
        ],
        "unit_inventory": [
            {
                "building_id": "SYNTH_SELFTEST",
                "openfdd_key": "AHU_1.fan_status",
                "role": "fan-status",
                "inventory_status": "ok",
                "point_map_unit": "1",
                "sample_unit": "1",
                "package_unit_system": "imperial",
                "w2c_source_unit": "imperial",
            }
        ],
        "sample_counts": [
            {"building_id": "SYNTH_SELFTEST", "table": "sample", "row_count": 10},
        ],
        "persisted_runs": [
            {
                "building_id": "SYNTH_SELFTEST",
                "run_id": "run-selftest",
                "window_start": "2026-06-01T00:00:00Z",
                "window_end": "2026-06-02T00:00:00Z",
            }
        ],
    }
    errors = validate_record_shapes(records)
    if errors:
        for err in errors:
            safe_print(f"FAIL self-test: {err}")
        return 1
    safe_print("PASS capture_ip_baseline --self-test shapes")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_connection_args(ap)
    for action in ap._actions:
        if action.dest == "password":
            action.default = None
            break
    ap.add_argument(
        "--database-url",
        default=None,
        help="Timescale URL for host-side capture (overrides OPENFDD_DATABASE_URL)",
    )
    ap.add_argument(
        "--oracle-source-root",
        type=Path,
        help="Explicit pinned open-fdd 4.4.9 source checkout used as the IP oracle",
    )
    ap.add_argument(
        "--jwt-env",
        type=Path,
        help="dotenv file with OPENFDD_API_BASE, OPENFDD_AGENT_PASSWORD, etc.",
    )
    ap.add_argument("--sites-config", type=Path, help="JSON list of sites (building_id, window)")
    ap.add_argument("--output-dir", type=Path, help="Override ~/openfdd-si-cutover/baseline-…")
    ap.add_argument("--skip-pandas", action="store_true", help="Skip pandas IP recompute")
    ap.add_argument(
        "--pandas-max-rules",
        type=int,
        default=0,
        help="If >0, limit pandas rules to first N in registry (recorded in manifest)",
    )
    ap.add_argument(
        "--rule-batch-size",
        type=int,
        default=0,
        help="If >0, run all SQL registry rules in batches of this size over the same full window",
    )
    ap.add_argument(
        "--allow-errors",
        action="store_true",
        help="Do not exit non-zero when any rule×equipment pair_status is error",
    )
    ap.add_argument(
        "--request-timeout-s",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_S,
        help=f"HTTP request timeout for capture calls (default {DEFAULT_REQUEST_TIMEOUT_S:g})",
    )
    ap.add_argument("--self-test", action="store_true", help="Offline JSON shape validation")
    ap.add_argument(
        "--emit-ip-goldens",
        type=Path,
        metavar="DIR",
        help="Write tests/fixtures/si_cutover/ip_goldens/*.json from capture output",
    )
    ap.add_argument(
        "--ci-fixtures-emit-goldens",
        type=Path,
        metavar="DIR",
        help="Offline: emit ip goldens from cookbook + SYNTH CI fixtures (no stack)",
    )
    args = ap.parse_args(argv)

    if args.request_timeout_s <= 0 or args.rule_batch_size < 0:
        ap.error("--request-timeout-s must be positive and --rule-batch-size non-negative")

    if args.self_test:
        return run_self_test()

    if args.ci_fixtures_emit_goldens:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from si_cutover.ci_fixtures_lib import emit_all_goldens

        url = os.environ.get("OPENFDD_DATABASE_URL", "").strip()
        if not url:
            raise SystemExit("--ci-fixtures-emit-goldens requires OPENFDD_DATABASE_URL")
        paths = emit_all_goldens(args.ci_fixtures_emit_goldens, database_url=url)
        safe_print(f"PASS ci-fixtures emit — {len(paths)} golden(s) → {args.ci_fixtures_emit_goldens}")
        return 0

    if not args.jwt_env or not args.sites_config:
        ap.error("--jwt-env and --sites-config are required unless --self-test")

    if not args.oracle_source_root:
        ap.error("--oracle-source-root is required for IP baseline capture")
    oracle = load_ip_oracle(args.oracle_source_root)
    if not args.skip_pandas:
        require_pandas_oracle()
    require_oracle_runtime(oracle)

    load_dotenv_file(args.jwt_env.expanduser())
    if args.database_url:
        os.environ["OPENFDD_DATABASE_URL"] = str(args.database_url).strip()
    require_database_url()
    sites = load_sites_config(args.sites_config.expanduser())
    rules = oracle["rules"]
    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    pandas_cap = args.pandas_max_rules if args.pandas_max_rules > 0 else None

    summaries: list[dict[str, Any]] = []
    all_errors: list[str] = []
    with HttpClient(base, timeout=args.request_timeout_s) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=resolve_capture_password(args))
        shortsha = health_shortsha(http, headers)
        out_dir = args.output_dir or default_output_dir(shortsha)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_print(f"baseline output: {out_dir}")
        with db_connect() as conn:
            for site in sites:
                safe_print(f"capture site {site.get('building_id')}")
                try:
                    summary = capture_site(
                        http,
                        headers,
                        conn,
                        site=site,
                        out_dir=out_dir,
                        rules=rules,
                        skip_pandas=args.skip_pandas,
                        pandas_max_rules=pandas_cap,
                        rule_batch_size=args.rule_batch_size,
                        request_timeout_s=args.request_timeout_s,
                    )
                except CaptureQualificationError as exc:
                    summary = {
                        "building_id": str(site.get("building_id") or "").strip(),
                        "disqualifying_reasons": [exc.reason],
                        "failed": True,
                    }
                summaries.append(summary)
                if summary.get("failed"):
                    continue
                all_errors.extend(summary.get("pandas_errors") or [])
                all_errors.extend(summary.get("analytics_errors") or [])
        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "health_shortsha": shortsha,
            "base_url": base,
            "skip_pandas": args.skip_pandas,
            "ip_oracle": {k: v for k, v in oracle.items() if k != "rules"},
            "pandas_max_rules": pandas_cap,
            "rule_batch_size": args.rule_batch_size,
            "allow_errors": args.allow_errors,
            "request_timeout_s": args.request_timeout_s,
            "sites": summaries,
        }
        disqualifiers = baseline_capture_disqualifiers(meta)
        meta["qualifying"] = not disqualifiers
        if disqualifiers:
            meta["disqualifying_reasons"] = disqualifiers
        write_manifest(out_dir, meta=meta)
        if args.emit_ip_goldens:
            emit_ip_goldens(out_dir, golden_dir=args.emit_ip_goldens, site_summaries=summaries)

    if all_errors and not args.allow_errors:
        safe_print(f"FAIL capture — {len(all_errors)} captured analytics/pandas error(s)")
        for msg in all_errors[:20]:
            safe_print(f"  {msg}")
        return 1
    if any(site.get("failed") for site in summaries if isinstance(site, dict)):
        safe_print("FAIL capture — site disqualification (see manifest disqualifying_reasons)")
        return 1
    safe_print(f"PASS capture — {len(summaries)} site(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
