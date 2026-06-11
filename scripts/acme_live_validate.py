#!/usr/bin/env python3
"""Deep live API validation for Acme Open-FDD edge (read-only by default)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
ANSIBLE_SCRIPTS = REPO / "infra" / "ansible" / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "workspace" / "api"))
sys.path.insert(0, str(ANSIBLE_SCRIPTS))

from scripts.acme_validation_report import (  # noqa: E402
    ValidationCheck,
    ValidationReport,
    print_console_summary,
    write_json_report,
    write_junit_report,
    write_markdown_report,
)

DEFAULT_PROFILE = {
    "site_id": "acme",
    "building_id": "vm-bbartling",
    "min_equipment_count": 10,
    "min_point_count": 50,
    "min_enabled_bacnet_points": 50,
    "max_recent_data_age_minutes": 30,
    "max_api_latency_ms": 3000,
    "max_container_restarts": 2,
    "max_disk_usage_percent": 85,
    "required_free_disk_gb": 5,
    "required_services": ["bridge", "commission"],
    "optional_services": ["mcp-rag", "cloud-exporter"],
    "required_rule_id_patterns": ["ahu", "vav"],
    "max_duplicate_bacnet_devices": 0,
    "max_duplicate_point_ids": 0,
    "critical_sparql_presets": [
        "rules_to_equipment",
        "rules_to_sensors",
        "rules_to_bacnet_devices",
        "equipment_to_points",
        "missing_rule_bindings",
        "orphan_points",
        "points_by_bacnet_device",
    ],
    "min_trend_samples": 3,
    "strict_fdd_in_full": True,
}

CRITICAL_SPARQL_PRESETS = DEFAULT_PROFILE["critical_sparql_presets"]
EQUIPMENT_TYPE_PRIORITY = ("ahu", "rtu", "vav", "boiler")


def normalize_image_tag(tag: str) -> str:
    return str(tag or "").removeprefix("v").strip()


def parse_container_image_tag(image: str) -> str:
    image = str(image or "").strip()
    if not image:
        return ""
    if "@" in image:
        image = image.split("@", 1)[0]
    if ":" in image:
        return image.rsplit(":", 1)[-1]
    return image


def normalize_service_name(name: str) -> str:
    raw = str(name or "").lower()
    for key in ("bridge", "commission", "mcp-rag", "mcp_rag", "cloud-exporter", "cloud_exporter"):
        if key.replace("-", "_") in raw.replace("-", "_") or raw == key:
            return key.replace("_", "-")
    return raw


def pick_equipment_for_rule_kit(bundle: dict[str, Any]) -> tuple[str | None, str]:
    """Choose equipment with rule bindings; prefer AHU/VAV/RTU from live model."""
    equipment = [e for e in bundle.get("equipment") or [] if isinstance(e, dict)]
    points = [p for p in bundle.get("points") or [] if isinstance(p, dict)]
    rule_ids = {str(r.get("id")) for r in bundle.get("fdd_rules") or [] if r.get("id")}
    bindings: Counter[str] = Counter()
    for pt in points:
        eq_id = str(pt.get("equipment_id") or "")
        if not eq_id:
            continue
        for rid in pt.get("fdd_rule_ids") or []:
            if str(rid) in rule_ids:
                bindings[eq_id] += 1
    candidates: list[tuple[int, int, str, str]] = []
    for eq in equipment:
        eq_id = str(eq.get("id") or "")
        if not eq_id or bindings[eq_id] <= 0:
            continue
        etype = str(eq.get("equipment_type") or eq.get("brick_type") or eq.get("name") or "").lower()
        prio = next((i for i, k in enumerate(EQUIPMENT_TYPE_PRIORITY) if k in etype), 99)
        candidates.append((prio, -bindings[eq_id], eq_id, etype or "equipment"))
    if not candidates:
        return None, "no equipment with fdd_rule_ids bindings"
    candidates.sort()
    best = candidates[0]
    return best[2], f"{best[3]} ({-best[1]} rule bindings)"


def validate_equipment_kit_zip(blob: bytes, equipment_id: str) -> tuple[list[str], dict[str, Any]]:
    """Return (errors, details) for equipment rule kit zip structure."""
    errors: list[str] = []
    details: dict[str, Any] = {"equipment_id": equipment_id}
    if not blob or blob[:2] != b"PK":
        return ["equipment kit response is not a zip"], details
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = zf.namelist()
        details["zip_entries"] = names[:20]
        if "manifest.json" not in names:
            errors.append("manifest.json missing from equipment kit zip")
            return errors, details
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        details["manifest"] = {
            "equipment_id": manifest.get("equipment_id"),
            "rules": len(manifest.get("rules") or []),
        }
        if str(manifest.get("equipment_id") or "") != equipment_id:
            errors.append(f"manifest equipment_id {manifest.get('equipment_id')!r} != {equipment_id!r}")
        rules = manifest.get("rules") or []
        if not rules:
            errors.append("equipment kit manifest has no rules")
        ok_rules = [r for r in rules if isinstance(r, dict) and r.get("status") == "ok"]
        if not ok_rules:
            errors.append("no rule with status=ok in equipment kit manifest")
        rule_prefixes = [n for n in names if n.startswith("rules/") and n.endswith(".py")]
        if not rule_prefixes:
            errors.append("no rule .py sources in equipment kit zip")
        has_config = any("column_map" in n or "config" in n.lower() for n in names)
        has_sample = any("sample" in n or ".feather" in n or "data.py" in n for n in names)
        has_result = any("result" in n.lower() for n in names) or bool(ok_rules)
        if not has_config:
            errors.append("equipment kit missing config/column_map artifact")
        if not has_sample:
            details["sample_warning"] = "no sample.feather/data.py — may be no historian data"
        if not has_result:
            errors.append("equipment kit missing result summary")
        expanded = [n for n in names if "expanded_source" in n]
        details["has_expanded_source"] = bool(expanded)
    return errors, details


def validate_trend_payload(payload: dict[str, Any], *, min_samples: int) -> tuple[list[str], list[str], dict[str, Any]]:
    """Return (errors, warnings, details) for /api/timeseries/readings JSON."""
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    row_count = int(payload.get("row_count") or 0)
    timestamps = payload.get("timestamps") or []
    if isinstance(timestamps, list) and timestamps:
        total_points = len(timestamps)
        details["point_count"] = total_points
        details["format"] = "timestamps+series"
        if total_points < min_samples:
            errors.append(f"trend returned {total_points} samples < min {min_samples}")
        series = payload.get("series")
        if isinstance(series, dict):
            non_null = 0
            for vals in series.values():
                if not isinstance(vals, list):
                    continue
                for val in vals:
                    if val is not None and val != "":
                        try:
                            float(val)
                            non_null += 1
                        except (TypeError, ValueError):
                            errors.append(f"non-numeric trend value: {val!r}")
                            return errors, warnings, details
            details["non_null_values"] = non_null
            if non_null == 0:
                errors.append("trend series are all null")
        return errors, warnings, details

    if row_count >= min_samples:
        details["point_count"] = row_count
        details["format"] = "row_count"
        return errors, warnings, details

    series = payload.get("series") or payload.get("columns") or payload.get("readings") or []
    if isinstance(payload.get("data"), list):
        series = payload["data"]
    details["series_count"] = len(series) if isinstance(series, list) else 0
    if not series:
        errors.append("trend response has no series/data")
        return errors, warnings, details
    total_points = 0
    all_null = True
    for item in series if isinstance(series, list) else []:
        if not isinstance(item, dict):
            continue
        pts = item.get("points") or item.get("values") or []
        for pt in pts if isinstance(pts, list) else []:
            if not isinstance(pt, dict):
                continue
            total_points += 1
            ts = pt.get("ts") or pt.get("timestamp") or pt.get("t")
            val = pt.get("value") if "value" in pt else pt.get("v")
            if ts is None:
                errors.append("trend point missing timestamp")
                break
            if val is not None:
                all_null = False
                try:
                    float(val)
                except (TypeError, ValueError):
                    if val not in (None, ""):
                        errors.append(f"non-numeric trend value: {val!r}")
                        break
        if errors:
            break
    details["point_count"] = total_points
    if total_points < min_samples:
        errors.append(f"trend returned {total_points} samples < min {min_samples}")
    if total_points and all_null:
        errors.append("trend series are all null")
    return errors, warnings, details


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"").strip()
    return out


def resolve_credentials(auth_env: Path, acme_secrets: Path | None) -> tuple[str, str]:
    auth = load_env_file(auth_env)
    acme = load_env_file(acme_secrets) if acme_secrets and acme_secrets.is_file() else {}
    user = acme.get("ACME_INTEGRATOR_USER") or auth.get("OFDD_INTEGRATOR_USER") or auth.get("OFDD_OPERATOR_USER") or ""
    password = (
        acme.get("ACME_INTEGRATOR_PASSWORD")
        or auth.get("OFDD_INTEGRATOR_PASSWORD")
        or auth.get("OFDD_OPERATOR_PASSWORD")
        or ""
    )
    return user, password


class ApiClient:
    def __init__(self, base: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> tuple[int, str, float]:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = self._headers() if auth and self.token else {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return resp.status, text, (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return exc.code, text, (time.perf_counter() - t0) * 1000
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

    def get_json(self, path: str, *, auth: bool = True) -> tuple[int, Any, float]:
        status, text, ms = self.request("GET", path, auth=auth)
        try:
            return status, json.loads(text) if text.strip() else {}, ms
        except json.JSONDecodeError:
            return status, {"_raw": text[:500]}, ms

    def post_json(self, path: str, body: dict[str, Any], *, auth: bool = True) -> tuple[int, Any, float]:
        status, text, ms = self.request("POST", path, body, auth=auth)
        try:
            return status, json.loads(text) if text.strip() else {}, ms
        except json.JSONDecodeError:
            return status, {"_raw": text[:500]}, ms


def scan_logs_for_fatal(text: str) -> list[str]:
    fatal_patterns = (
        "Traceback",
        "Unhandled exception",
        "ModuleNotFoundError",
        "ImportError",
        "SyntaxError",
        "database is locked",
        "Address already in use",
    )
    hits: list[str] = []
    for pat in fatal_patterns:
        if pat in text:
            hits.append(pat)
    return hits


class AcmeLiveValidator:
    def __init__(
        self,
        *,
        base: str,
        site_id: str,
        building_id: str,
        profile: dict[str, Any],
        expected_image_tag: str = "",
        auth_env: Path,
        acme_secrets: Path | None = None,
        mode: str = "quick",
        skip_ui: bool = False,
        skip_bacnet: bool = False,
        skip_fdd: bool = False,
        skip_rulelab: bool = False,
        skip_logs: bool = False,
        fail_fast: bool = False,
        strict_fdd: bool | None = None,
        local_ui_index: Path | None = None,
        remote_host_json: dict[str, Any] | None = None,
    ) -> None:
        self.base = base.rstrip("/")
        self.site_id = site_id
        self.building_id = building_id
        self.profile = {**DEFAULT_PROFILE, **profile}
        self.expected_image_tag = expected_image_tag.strip()
        self.auth_env = auth_env
        self.acme_secrets = acme_secrets
        self.mode = mode
        self.skip_ui = skip_ui
        self.skip_bacnet = skip_bacnet
        self.skip_fdd = skip_fdd
        self.skip_rulelab = skip_rulelab
        self.skip_logs = skip_logs
        self.fail_fast = fail_fast
        if strict_fdd is None:
            strict_fdd = mode in {"full", "long"} and bool(self.profile.get("strict_fdd_in_full", True))
        self.strict_fdd = strict_fdd
        self.local_ui_index = local_ui_index or (REPO / "workspace/api/static/app/index.html")
        self.remote_host_json = remote_host_json or {}
        self.token: str | None = None
        self.client = ApiClient(self.base)
        self.report = ValidationReport(
            target={
                "base_url": "redacted",
                "site_id": site_id,
                "building_id": building_id,
                "expected_image_tag": expected_image_tag,
                "mode": mode,
            },
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def _run_check(self, check_id: str, category: str, fn: Callable[[], tuple[str, str, dict[str, Any]]]) -> None:
        t0 = time.perf_counter()
        try:
            status, message, details = fn()
        except Exception as exc:  # noqa: BLE001
            status, message, details = "fail", str(exc), {}
        ms = int((time.perf_counter() - t0) * 1000)
        self.report.add(
            ValidationCheck(
                id=check_id,
                category=category,
                status=status,  # type: ignore[arg-type]
                duration_ms=ms,
                message=message,
                details=details,
            )
        )
        if self.fail_fast and status == "fail":
            raise SystemExit(1)

    def login(self) -> None:
        user, password = resolve_credentials(self.auth_env, self.acme_secrets)
        if not user or not password:
            self.report.add(
                ValidationCheck(
                    id="auth_credentials",
                    category="auth",
                    status="fail",
                    message="No integrator credentials in auth env or acme secrets",
                )
            )
            return
        status, body, ms = self.client.request(
            "POST",
            "/api/auth/login",
            {"username": user, "password": password},
            auth=False,
        )
        if status != 200:
            self.report.add(
                ValidationCheck(
                    id="auth_login",
                    category="auth",
                    status="fail",
                    duration_ms=int(ms),
                    message=f"Login failed HTTP {status}",
                    details={"body_preview": body[:200]},
                )
            )
            return
        self.token = json.loads(body)["token"]
        self.client = ApiClient(self.base, self.token)
        self.report.add(
            ValidationCheck(
                id="auth_login",
                category="auth",
                status="pass",
                duration_ms=int(ms),
                message="Authenticated as integrator",
            )
        )

    def validate_all(self) -> ValidationReport:
        self.login()
        if not self.token:
            self.report.finalize()
            return self.report

        self._run_check("bridge_health", "api", self._check_bridge_health)
        self._run_check("auth_required_routes", "auth", self._check_auth_required)
        if not self.skip_ui:
            self._run_check("ui_bundle_freshness", "ui", self._check_ui_bundle)
        self._run_check("docker_image_tag", "docker", self._check_docker_image_tag)
        if self.remote_host_json:
            self._run_check("remote_host_containers", "docker", self._check_remote_host)
        self._run_check("model_health", "model", self._check_model_health)
        self._run_check("no_duplicate_devices", "model", self._check_no_duplicate_devices)
        self._run_check("commissioning_export", "model", self._check_commissioning_export)
        if self.mode in {"full", "long"}:
            self._run_check("sparql_presets", "model", self._check_sparql)
        if not self.skip_bacnet:
            self._run_check("bacnet_poll", "bacnet", self._check_bacnet_poll)
        self._run_check("historian_trends", "historian", self._check_trends)
        if not self.skip_fdd:
            self._run_check("fdd_rules_batch", "fdd", self._check_fdd)
            self._run_check("building_status_context", "building", self._check_building_status)
        if not self.skip_rulelab and self.mode in {"full", "long"}:
            self._run_check("rule_lab_export", "rulelab", self._check_rule_lab)
        self._run_check("host_resources", "host", self._check_host_resources)
        self._run_check("security_redaction", "security", self._check_security)
        if not self.skip_logs:
            self._run_check("logs_scan", "logs", self._check_logs)
        if self.mode in {"full", "long"}:
            self._run_check("bundle_validator", "local", self._check_local_bundle)
            self._run_check("pypi_rules_smoke", "local", self._check_pypi_rules)

        self.report.finalize()
        return self.report

    def _check_bridge_health(self) -> tuple[str, str, dict[str, Any]]:
        status, body, ms = self.client.request("GET", "/health", auth=False)
        if status != 200:
            return "fail", f"/health HTTP {status}", {"latency_ms": ms}
        data = json.loads(body)
        latency_limit = float(self.profile.get("max_api_latency_ms", 3000))
        if ms > latency_limit:
            return "warn", f"Health latency {ms:.0f}ms > {latency_limit:.0f}ms", data
        ver = data.get("openfdd_version") or data.get("version")
        return "pass", f"Bridge health OK (version={ver})", {**data, "latency_ms": ms}

    def _check_auth_required(self) -> tuple[str, str, dict[str, Any]]:
        status, _, _ = self.client.get_json("/api/model/health", auth=False)
        if status == 401:
            return "pass", "Model health requires auth", {}
        return "fail", f"Expected 401 without token, got {status}", {}

    def _check_ui_bundle(self) -> tuple[str, str, dict[str, Any]]:
        status, html, _ = self.client.request("GET", "/", auth=False)
        if status != 200:
            return "fail", f"Dashboard HTML HTTP {status}", {}
        m = re.search(r'src="([^"]*index-[^"]+\.js)"', html)
        if not m:
            return "fail", "No index-*.js bundle in dashboard HTML", {}
        remote_asset = m.group(1)
        if not remote_asset.startswith("/"):
            remote_asset = "/" + remote_asset.lstrip("/")
        a_status, _, _ = self.client.request("GET", remote_asset, auth=False)
        if a_status != 200:
            return "fail", f"JS bundle {remote_asset} HTTP {a_status}", {}
        local_asset = ""
        if self.local_ui_index.is_file():
            local_html = self.local_ui_index.read_text(encoding="utf-8")
            lm = re.search(r'src="([^"]*index-[^"]+\.js)"', local_html)
            if lm:
                local_asset = lm.group(1).split("/")[-1]
        remote_name = remote_asset.split("/")[-1]
        details = {"remote_bundle": remote_name, "local_bundle": local_asset or None}
        if local_asset and local_asset != remote_name:
            return (
                "fail",
                f"Stale UI bundle on edge: remote={remote_name} local={local_asset} — run upgrade_edge_full.sh",
                details,
            )
        return "pass", f"UI bundle {remote_name} reachable", details

    def _check_docker_image_tag(self) -> tuple[str, str, dict[str, Any]]:
        from http_probes import check_stack_revision  # type: ignore[import-untyped]

        rev = check_stack_revision(self.base, self.token or "", expected_image_tag=self.expected_image_tag)
        tag = str(rev.get("image_tag") or "")
        details = {"image_tag": tag, "git_sha": rev.get("git_sha")}
        expected = self.expected_image_tag
        if expected and expected != "latest":
            norm_expected = normalize_image_tag(expected)
            norm_tag = normalize_image_tag(tag)
            if tag and norm_tag and norm_tag != norm_expected:
                return "fail", f"Running tag {tag!r} != expected {expected!r}", details
        if rev.get("errors"):
            return "fail", "; ".join(rev["errors"]), details
        if rev.get("warnings"):
            return "warn", "; ".join(rev["warnings"]), details
        return "pass", f"Bridge image tag {tag or 'unknown'}", details

    def _check_remote_host(self) -> tuple[str, str, dict[str, Any]]:
        data = self.remote_host_json
        services = data.get("compose_services") or data.get("services") or []
        required = {normalize_service_name(s) for s in (self.profile.get("required_services") or [])}
        optional = {normalize_service_name(s) for s in (self.profile.get("optional_services") or [])}
        running: dict[str, dict[str, Any]] = {}
        for svc in services:
            if not isinstance(svc, dict):
                continue
            name = normalize_service_name(str(svc.get("service") or svc.get("name") or ""))
            if name:
                running[name] = svc
        missing = [s for s in required if s not in running]
        restarts = int(data.get("max_restart_count") or 0)
        max_restarts = int(self.profile.get("max_container_restarts", 2))
        tag_details: dict[str, str] = {}
        tag_errors: list[str] = []
        expected_norm = normalize_image_tag(self.expected_image_tag)
        if expected_norm and expected_norm != "latest":
            for svc_name, row in running.items():
                image = str(row.get("image") or "")
                tag = normalize_image_tag(parse_container_image_tag(image))
                if tag:
                    tag_details[svc_name] = tag
                if svc_name in required and tag and tag != expected_norm:
                    tag_errors.append(f"{svc_name} tag {tag!r} != expected {expected_norm!r}")
                if svc_name in optional and tag and tag != expected_norm:
                    tag_errors.append(f"optional {svc_name} running with wrong tag {tag!r}")
        data = {**data, "service_image_tags": tag_details}
        if missing:
            return "fail", f"Missing services: {missing}", data
        if tag_errors:
            return "fail", "; ".join(tag_errors), data
        if restarts > max_restarts:
            return "fail", f"Container restarts {restarts} > {max_restarts}", data
        disk_pct = data.get("disk_usage_percent")
        if disk_pct is not None and float(disk_pct) > float(self.profile.get("max_disk_usage_percent", 85)):
            return "warn", f"Disk usage {disk_pct}% high", data
        msg = f"Remote host OK ({len(running)} services)"
        if tag_details:
            msg += f" tags={tag_details}"
        return "pass", msg, data

    def _check_model_health(self) -> tuple[str, str, dict[str, Any]]:
        status, data, ms = self.client.get_json("/api/model/health")
        if status != 200:
            return "fail", f"/api/model/health HTTP {status}", {}
        counts = data.get("counts") or {}
        eq = int(counts.get("equipment") or 0)
        pts = int(counts.get("points") or 0)
        min_eq = int(self.profile.get("min_equipment_count", 10))
        min_pts = int(self.profile.get("min_point_count", 50))
        details = {"counts": counts, "score": data.get("score"), "latency_ms": ms}
        if eq < min_eq or pts < min_pts:
            return "fail", f"Model counts low: equipment={eq} points={pts}", details
        dup = int(counts.get("duplicate_bacnet_device_instances") or 0)
        dup_pts = int(counts.get("duplicate_point_ids") or 0)
        if dup > int(self.profile.get("max_duplicate_bacnet_devices", 0)):
            return "fail", f"{dup} duplicate BACnet device instance(s) in model", details
        if dup_pts > int(self.profile.get("max_duplicate_point_ids", 0)):
            return "fail", f"{dup_pts} duplicate point id(s) in model", details
        if data.get("status") == "error":
            return "fail", f"Model health status=error score={data.get('score')}", details
        return "pass", f"Model health OK (equipment={eq}, points={pts}, score={data.get('score')})", details

    def _check_no_duplicate_devices(self) -> tuple[str, str, dict[str, Any]]:
        """Explicit duplicate BACnet device + point ID gate (model + poll inventory)."""
        status, bundle, _ = self.client.get_json("/api/model/commissioning-export")
        details: dict[str, Any] = {}
        if status == 200:
            equipment = bundle.get("equipment") or []
            points = bundle.get("points") or []
            dev_ids = [e.get("bacnet_device_id") for e in equipment if e.get("bacnet_device_id") is not None]
            dup_dev = {k: v for k, v in Counter(dev_ids).items() if v > 1}
            pid = Counter(str(p.get("id")) for p in points if p.get("id"))
            dup_pid = {k: v for k, v in pid.items() if v > 1}
            details["duplicate_bacnet_device_ids"] = dup_dev
            details["duplicate_point_ids"] = dup_pid
            max_dev = int(self.profile.get("max_duplicate_bacnet_devices", 0))
            max_pid = int(self.profile.get("max_duplicate_point_ids", 0))
            if dup_dev:
                return "fail", f"Duplicate BACnet device IDs in model: {dup_dev}", details
            if dup_pid:
                return "fail", f"Duplicate point IDs in model: {list(dup_pid.keys())[:5]}", details
        if not self.skip_bacnet:
            st, inv, _ = self.client.get_json("/api/bacnet/inventory")
            if st == 200:
                devices = inv.get("devices") or []
                inst = [str(d.get("device_instance") or d.get("instance") or "") for d in devices]
                inst = [i for i in inst if i]
                dup_inst = {k: v for k, v in Counter(inst).items() if v > 1}
                details["poll_inventory_duplicate_instances"] = dup_inst
                if dup_inst:
                    return "fail", f"Duplicate BACnet instances in poll inventory: {dup_inst}", details
                details["poll_device_count"] = len(devices)
        if details:
            return "pass", "No duplicate BACnet devices or point IDs", details
        return "warn", "Could not verify duplicates (export/inventory unavailable)", details

    def _check_commissioning_export(self) -> tuple[str, str, dict[str, Any]]:
        status, bundle, _ = self.client.get_json("/api/model/commissioning-export")
        if status != 200:
            return "fail", f"commissioning-export HTTP {status}", {}
        sites = bundle.get("sites") or []
        eq = bundle.get("equipment") or []
        pts = bundle.get("points") or []
        site_ids = {s.get("id") for s in sites}
        if self.site_id not in site_ids:
            return "fail", f"Site {self.site_id!r} missing from export", {"sites": list(site_ids)}
        rule_ids = {r.get("id") for r in (bundle.get("fdd_rules") or []) if r.get("id")}
        bad_refs = 0
        for p in pts:
            for rid in p.get("fdd_rule_ids") or []:
                if rid not in rule_ids:
                    bad_refs += 1
        details = {
            "equipment_count": len(eq),
            "point_count": len(pts),
            "fdd_rules_count": len(rule_ids),
            "invalid_rule_refs": bad_refs,
        }
        if bad_refs:
            return "fail", f"{bad_refs} point(s) reference missing fdd_rule_ids", details
        return "pass", f"Commissioning export OK ({len(eq)} equipment, {len(pts)} points)", details

    def _check_sparql(self) -> tuple[str, str, dict[str, Any]]:
        status, presets, _ = self.client.get_json("/api/model/fdd-query-presets")
        if status != 200:
            return "fail", f"fdd-query-presets HTTP {status}", {}
        preset_list = presets if isinstance(presets, list) else presets.get("presets") or []
        available = {str(p.get("preset_id") or p.get("id") or "") for p in preset_list if isinstance(p, dict)}
        critical = [str(p) for p in (self.profile.get("critical_sparql_presets") or CRITICAL_SPARQL_PRESETS)]
        missing = [p for p in critical if p not in available]
        if missing:
            return "fail", f"Missing critical SPARQL presets: {missing}", {"available": sorted(available)}
        results: dict[str, Any] = {}
        errors: list[str] = []
        empty_warn: list[str] = []
        for pid in critical:
            st, result, _ = self.client.get_json(f"/api/model/fdd-query-presets/{urllib.parse.quote(pid)}")
            if st != 200:
                errors.append(f"{pid} HTTP {st}")
                continue
            rows = result.get("rows") or result.get("results") or []
            row_count = len(rows) if isinstance(rows, list) else 0
            results[pid] = row_count
            if row_count == 0 and pid not in {"orphan_points", "missing_rule_bindings"}:
                empty_warn.append(pid)
        details = {"preset_rows": results, "empty_presets": empty_warn}
        if errors:
            return "fail", "; ".join(errors), details
        if empty_warn and self.mode in {"full", "long"}:
            return "warn", f"SPARQL presets returned 0 rows: {empty_warn}", details
        return "pass", f"All {len(critical)} critical SPARQL presets OK", details

    def _check_bacnet_poll(self) -> tuple[str, str, dict[str, Any]]:
        from http_probes import check_bacnet_driver  # type: ignore[import-untyped]

        min_dev = 1
        min_pts = int(self.profile.get("min_enabled_bacnet_points", 50))
        out = check_bacnet_driver(self.base, self.token or "", min_devices=min_dev, min_enabled_points=min_pts)
        if out.get("errors"):
            return "fail", "; ".join(out["errors"]), out
        if out.get("warnings"):
            return "warn", "; ".join(out["warnings"]), out
        return "pass", "BACnet poll pipeline healthy", out

    def _check_trends(self) -> tuple[str, str, dict[str, Any]]:
        from http_probes import check_integrator_ui_api  # type: ignore[import-untyped]

        ui = check_integrator_ui_api(self.base, self.token or "", site_id=self.site_id)
        details: dict[str, Any] = dict(ui)
        if ui.get("errors"):
            return "fail", "; ".join(ui["errors"]), details

        st, bundle, _ = self.client.get_json("/api/model/commissioning-export")
        trend_col = ""
        trend_point = ""
        if st == 200:
            for pt in bundle.get("points") or []:
                if not isinstance(pt, dict):
                    continue
                col = str(pt.get("external_id") or pt.get("fdd_input") or pt.get("id") or "").strip()
                if col and pt.get("enabled", True) is not False:
                    trend_col = col
                    trend_point = str(pt.get("id") or col)
                    break
        if not trend_col:
            if ui.get("warnings"):
                return "warn", "; ".join(ui["warnings"]), details
            return "warn", "No model point for trend probe (commissioning export empty?)", details

        hours = 24
        url = (
            f"/api/timeseries/readings?site_id={urllib.parse.quote(self.site_id)}"
            f"&columns={urllib.parse.quote(trend_col)}"
            f"&hours={hours}&include_faults=false&rolling_avg_minutes=5&show_rolling_avg=true"
        )
        t_status, trend_payload, _ = self.client.get_json(url)
        details["trend_point_id"] = trend_point
        details["trend_column"] = trend_col
        details["trend_hours"] = hours
        if t_status == 404:
            return "warn", f"No historian data for {trend_col} (poll warming up?)", details
        if t_status != 200:
            return "fail", f"/api/timeseries/readings HTTP {t_status} for {trend_col}", details
        min_samples = int(self.profile.get("min_trend_samples", 3))
        terr, twarn, tdet = validate_trend_payload(trend_payload, min_samples=min_samples)
        details.update(tdet)
        if terr:
            return "fail", "; ".join(terr), details
        warns = list(ui.get("warnings") or []) + twarn
        if warns:
            return "warn", "; ".join(warns), details
        return "pass", f"Trend data OK for {trend_col} ({tdet.get('point_count', 0)} samples)", details

    def _check_fdd(self) -> tuple[str, str, dict[str, Any]]:
        from http_probes import check_fdd_operational  # type: ignore[import-untyped]

        min_rules = 5
        out = check_fdd_operational(
            self.base,
            self.token or "",
            site_id=self.site_id,
            min_saved_rules=min_rules,
        )
        patterns = [p.lower() for p in (self.profile.get("required_rule_id_patterns") or [])]
        status, saved, _ = self.client.get_json("/api/rules/saved")
        if status == 200:
            rules = saved.get("rules") or []
            enabled_ids = [str(r.get("id") or "") for r in rules if r.get("enabled") is not False]
            for pat in patterns:
                if not any(pat in rid.lower() for rid in enabled_ids):
                    out.setdefault("warnings", []).append(f"No enabled rule matching pattern {pat!r}")
        st, results, _ = self.client.get_json("/api/fdd/results?limit=20")
        if st == 200:
            runs = results.get("runs") or results if isinstance(results, list) else []
            if isinstance(results, dict):
                runs = results.get("runs") or []
            out["fdd_result_runs"] = len(runs)
        if out.get("errors"):
            return "fail", "; ".join(out["errors"]), out
        if out.get("warnings"):
            return "warn", "; ".join(out["warnings"]), out
        return "pass", f"FDD rules operational ({out.get('rules_enabled_count', '?')} enabled)", out

    def _check_building_status(self) -> tuple[str, str, dict[str, Any]]:
        from http_probes import check_building_dashboard_health  # type: ignore[import-untyped]

        dash = check_building_dashboard_health(self.base, self.token or "", site_id=self.site_id)
        st, faults, _ = self.client.get_json("/api/faults/status")
        missing_ctx = 0
        fdd_without_equipment = 0
        fdd_count = 0
        if st == 200:
            for fam in faults.get("families") or []:
                for alert in fam.get("faults") or []:
                    if alert.get("source") != "fdd":
                        continue
                    fdd_count += 1
                    ctx = alert.get("model_context") or {}
                    if not (ctx.get("equipment") or alert.get("equipment_name") or alert.get("equipment_id")):
                        fdd_without_equipment += 1
                    has_point = bool(
                        ctx.get("point")
                        or ctx.get("historian_column")
                        or alert.get("point_id")
                        or alert.get("external_id")
                        or alert.get("fdd_input")
                    )
                    if not has_point:
                        missing_ctx += 1
        dash["fdd_alert_count"] = fdd_count
        dash["fdd_missing_equipment_context"] = fdd_without_equipment
        dash["fdd_missing_point_context"] = missing_ctx
        if fdd_count == 0 and self.mode in {"full", "long"}:
            if st != 200:
                return "fail", f"/api/faults/status HTTP {st}", dash
            if "families" not in faults:
                return "fail", "faults/status missing families schema", dash
        if fdd_without_equipment or missing_ctx:
            return (
                "fail",
                f"Building Status: {fdd_without_equipment} FDD alert(s) missing equipment, "
                f"{missing_ctx} missing point context",
                dash,
            )
        if dash.get("errors"):
            return "fail", "; ".join(dash["errors"]), dash
        if dash.get("warnings"):
            return "warn", "; ".join(dash["warnings"]), dash
        return "pass", "Building Status fault context OK", dash

    def _check_rule_lab(self) -> tuple[str, str, dict[str, Any]]:
        st, _, _ = self.client.post_json(
            "/api/playground/lint",
            {"code": "def apply_faults_arrow(table, cfg, context):\n    return table", "mode": "rule"},
        )
        if st != 200:
            return "fail", f"playground lint HTTP {st}", {}
        st, bundle, _ = self.client.get_json("/api/model/commissioning-export")
        if st != 200:
            return "fail", f"commissioning-export HTTP {st} (equipment discovery)", {}
        eq_id, pick_reason = pick_equipment_for_rule_kit(bundle)
        details: dict[str, Any] = {"equipment_pick": pick_reason}
        if not eq_id:
            if self.mode == "quick":
                return "warn", pick_reason, details
            return "fail", pick_reason, details
        details["equipment_id"] = eq_id
        st, saved, _ = self.client.get_json("/api/rules/saved")
        rules = (saved.get("rules") or []) if st == 200 else []
        enabled = [r for r in rules if isinstance(r, dict) and r.get("enabled") is not False]
        if enabled:
            rid = str(enabled[0].get("id") or "")
            details["rule_id"] = rid
            st2, body, _ = self.client.request(
                "GET",
                f"/api/playground/rules/{urllib.parse.quote(rid)}/source-expanded",
            )
            if st2 == 200:
                try:
                    expanded = json.loads(body)
                    if expanded.get("source") or expanded.get("expanded_source") or expanded.get("rule_source"):
                        details["source_expanded"] = True
                except json.JSONDecodeError:
                    pass
        url = (
            f"{self.base}/api/rules/export-equipment-kit?"
            f"equipment_id={urllib.parse.quote(eq_id)}&site_id={urllib.parse.quote(self.site_id)}"
        )
        req = urllib.request.Request(url, headers=self.client._headers())
        try:
            with urllib.request.urlopen(req, timeout=max(self.client.timeout, 60)) as resp:
                blob = resp.read()
        except urllib.error.HTTPError as exc:
            details["export_http"] = exc.code
            return "fail", f"equipment kit export HTTP {exc.code} for {eq_id}", details
        kit_errors, kit_details = validate_equipment_kit_zip(blob, eq_id)
        details.update(kit_details)
        if kit_errors:
            return "fail", "; ".join(kit_errors), details
        if details.get("sample_warning"):
            return "warn", f"Equipment kit OK for {eq_id} ({details['sample_warning']})", details
        return "pass", f"Equipment rule kit zip OK for {eq_id}", details

    def _check_host_resources(self) -> tuple[str, str, dict[str, Any]]:
        st, stats, _ = self.client.get_json("/api/host/stats")
        if st != 200:
            return "fail", f"/api/host/stats HTTP {st}", {}
        disk = stats.get("disk") or {}
        free_gb = float(disk.get("free_gb") or disk.get("free_gib") or 0)
        used_pct = float(disk.get("used_percent") or disk.get("usage_percent") or 0)
        req_free = float(self.profile.get("required_free_disk_gb", 5))
        if free_gb and free_gb < req_free:
            return "warn", f"Low workspace disk free {free_gb:.1f}GB", stats
        if used_pct > float(self.profile.get("max_disk_usage_percent", 85)):
            return "warn", f"Disk usage {used_pct}%", stats
        st2, preview, _ = self.client.post_json(
            "/api/host/pooge/preview",
            {"dry_run": True, "confirmation": ""},
        )
        if st2 == 200 and preview.get("would_run"):
            return "fail", "Pooge preview would run without confirmation (unsafe)", preview
        return "pass", "Host resources OK", stats

    def _check_security(self) -> tuple[str, str, dict[str, Any]]:
        st, body, _ = self.client.request("GET", "/api/auth/login", auth=False)
        if st not in (401, 405):
            pass
        st2, inv, _ = self.client.get_json("/api/bacnet/inventory")
        text = json.dumps(inv) if isinstance(inv, dict) else ""
        if "password" in text.lower() or "secret" in text.lower():
            return "fail", "BACnet inventory may expose secrets", {}
        invalid_st, _, _ = self.client.get_json("/api/model/health", auth=False)
        if invalid_st != 401:
            return "fail", f"Unauthenticated model health returned {invalid_st}", {}
        return "pass", "Auth and redaction checks OK", {}

    def _check_logs(self) -> tuple[str, str, dict[str, Any]]:
        st, logs, _ = self.client.get_json("/api/ops/logs?tail=80&include_docker=true")
        if st != 200:
            return "warn", f"ops/logs HTTP {st} (skipped)", {}
        text = json.dumps(logs) if isinstance(logs, dict) else str(logs)
        hits = scan_logs_for_fatal(text)
        if hits:
            return "fail", f"Fatal log patterns: {hits}", {"patterns": hits}
        return "pass", "No fatal log patterns in recent ops logs", {}

    def _check_local_bundle(self) -> tuple[str, str, dict[str, Any]]:
        script = REPO / "scripts/acme_validate_fdd_bundle.py"
        if not script.is_file():
            return "skip", "acme_validate_fdd_bundle.py missing", {}
        out_path = REPO / "reports" / ".acme-bundle-check.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(script), "--json-out", str(out_path), "--site-id", self.site_id],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            return "fail", "Local FDD bundle validation failed", {"stderr": proc.stderr[:400]}
        return "pass", "Local Acme FDD bundle validation OK", {}

    def _check_pypi_rules(self) -> tuple[str, str, dict[str, Any]]:
        script = REPO / "scripts/validate_acme_rules_pypi.py"
        if not script.is_file():
            return "skip", "validate_acme_rules_pypi.py missing", {}
        try:
            import open_fdd.arrow_runtime  # noqa: F401
        except ModuleNotFoundError:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-e", f"{REPO}[dev,test]"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if proc.returncode != 0:
                msg = "PyPI rule smoke skipped (open-fdd package not installed)"
                details = {"stderr": proc.stderr[:400]}
                if self.strict_fdd and not self.skip_fdd:
                    return "fail", msg, details
                return "warn", msg, details
        env = {**os.environ, "PYTHONPATH": f"{REPO}:{REPO / 'workspace' / 'api'}"}
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            env=env,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            msg = "PyPI-style rule smoke failed"
            details = {"stderr": proc.stderr[:400], "stdout": proc.stdout[:400]}
            if self.strict_fdd and not self.skip_fdd:
                return "fail", msg, details
            return "warn", f"{msg} (non-blocking in quick mode)", details
        return "pass", "PyPI-style Acme rule smoke OK", {}


def load_profile(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"Profile not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_base_from_ansible(limit: str) -> str:
    secrets = REPO / "infra/ansible/secrets/acme.env.local"
    if limit == "acme_vm_bbartling" and secrets.is_file():
        env = load_env_file(secrets)
        host = env.get("ACME_SSH_HOST") or env.get("ACME_DASHBOARD_URL", "").replace("http://", "").replace("https://", "").split("/")[0]
        if host:
            return f"http://{host}"
    inv = REPO / "infra/ansible/inventory.yml"
    if inv.is_file():
        text = inv.read_text(encoding="utf-8")
        m = re.search(rf"{re.escape(limit)}:\s*\n\s*ansible_host:\s*(\S+)", text)
        if m:
            return f"http://{m.group(1)}"
    raise SystemExit(
        f"Cannot resolve base URL for --limit {limit!r}. "
        "Set --base or configure infra/ansible/secrets/acme.env.local (gitignored)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--limit", default="")
    parser.add_argument("--site-id", default="acme")
    parser.add_argument("--building-id", default="vm-bbartling")
    parser.add_argument("--expected-image-tag", default=os.environ.get("OPENFDD_IMAGE_TAG", ""))
    parser.add_argument("--auth-env", default=str(REPO / "workspace/auth.env.local"))
    parser.add_argument("--acme-secrets", default=str(REPO / "infra/ansible/secrets/acme.env.local"))
    parser.add_argument("--profile", default="")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--junit-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--remote-host-json", default="")
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--skip-bacnet", action="store_true")
    parser.add_argument("--skip-fdd", action="store_true")
    parser.add_argument("--skip-rulelab", action="store_true")
    parser.add_argument("--skip-logs", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--strict-fdd", action="store_true", help="Fail on PyPI/rule smoke errors (default in --full)")
    parser.add_argument("--no-strict-fdd", action="store_true", help="Allow PyPI rule smoke to warn even in --full")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args(argv)

    if args.allow_write:
        print("error: --allow-write not used in read-only validation harness", file=sys.stderr)
        return 2

    mode = "quick"
    if args.full:
        mode = "full"
    elif args.long:
        mode = "long"

    base = args.base.strip()
    if not base:
        if args.limit:
            base = resolve_base_from_ansible(args.limit)
        else:
            parser.error("Provide --base or --limit")

    profile = load_profile(args.profile or None)
    remote_host: dict[str, Any] | None = None
    if args.remote_host_json:
        remote_host = json.loads(Path(args.remote_host_json).read_text(encoding="utf-8"))

    strict_fdd: bool | None = None
    if args.strict_fdd:
        strict_fdd = True
    elif args.no_strict_fdd:
        strict_fdd = False

    t0 = time.perf_counter()
    validator = AcmeLiveValidator(
        base=base,
        site_id=args.site_id,
        building_id=args.building_id,
        profile=profile,
        expected_image_tag=args.expected_image_tag,
        auth_env=Path(args.auth_env),
        acme_secrets=Path(args.acme_secrets) if args.acme_secrets else None,
        mode=mode,
        skip_ui=args.skip_ui,
        skip_bacnet=args.skip_bacnet,
        skip_fdd=args.skip_fdd,
        skip_rulelab=args.skip_rulelab,
        skip_logs=args.skip_logs,
        fail_fast=args.fail_fast,
        strict_fdd=strict_fdd,
        remote_host_json=remote_host,
    )
    report = validator.validate_all()
    report.duration_seconds = time.perf_counter() - t0
    print_console_summary(report)
    if args.json_out:
        write_json_report(report, args.json_out)
        print(f"\nReport: {args.json_out}")
    if args.junit_out:
        write_junit_report(report, args.junit_out)
    if args.markdown_out:
        write_markdown_report(report, args.markdown_out)
    return 0 if report.summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
