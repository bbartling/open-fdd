"""Probe orchestration: dry-run plan vs execute."""
from __future__ import annotations

from pathlib import Path

from . import __version__
from .config import (
    ConfigError,
    assert_base_url_allowed,
    budget_for,
    load_config,
    validate_profile_suite,
)
from .evidence import CheckResult, SecurityReport, now_iso, write_report
from .inventory import inventory_summary, load_inventory
from .profiles import required_check_ids
from .suites import SUITE_RUNNERS, SuiteContext
from .transport import Budget, SafeHttpClient


def list_suites() -> dict[str, str]:
    return {
        "X": "authentication / JWT / preauth",
        "Y": "authorization A/B + roles",
        "Z": "deployment headers / CORS / abuse bounds",
        "mqtt_acl": "optional isolated broker ACL (distinct from continuity)",
    }


def plan_checks(profile: str, suites: list[str]) -> list[str]:
    return required_check_ids(profile, suites)


def run_probe(
    *,
    config_path: Path,
    base_url: str,
    profile: str,
    suites: list[str] | None,
    execute: bool,
    dry_run: bool,
    max_requests: int | None,
    timeout: float | None,
    deadline: float | None,
    rate: float | None,
    output_dir: Path | None,
    allow_fixture_writes: bool,
    isolated_jwt_secret: bytes | None = None,
) -> tuple[SecurityReport, dict[str, str] | None]:
    if execute and dry_run:
        raise ConfigError("--execute conflicts with --dry-run")
    if not execute:
        dry_run = True

    cfg = load_config(config_path)
    origin = assert_base_url_allowed(base_url, cfg, profile)
    suite_list = validate_profile_suite(profile, suites)
    full_profile = suites is None

    bud = budget_for(profile)
    if max_requests is not None:
        bud["max_requests"] = max_requests
    if timeout is not None:
        bud["timeout_s"] = timeout
    if deadline is not None:
        bud["deadline_s"] = deadline
    if rate is not None:
        bud["rate_rps"] = rate

    if allow_fixture_writes and profile == "live_readonly":
        raise ConfigError("live_readonly forbids --allow-fixture-writes")
    if allow_fixture_writes and not bud.get("allow_writes"):
        raise ConfigError(f"profile {profile} forbids fixture writes")

    inv = load_inventory()
    report = SecurityReport(
        profile=profile,
        origin=origin,
        executed=False,
        dry_run=dry_run,
        suites=suite_list,
        full_profile=full_profile,
        started_at=now_iso(),
        budget=bud,
        inventory=inventory_summary(inv),
        harness={"version": __version__},
        notes=[],
    )

    planned = plan_checks(profile, suite_list)
    if dry_run:
        for check_id in planned:
            if check_id.startswith("y."):
                suite = "Y"
            elif check_id.startswith("z."):
                suite = "Z"
            elif check_id.startswith("mqtt"):
                suite = "mqtt_acl"
            else:
                suite = "X"
            report.add(
                CheckResult(
                    check_id=check_id,
                    suite=suite,
                    title=f"planned:{check_id}",
                    status="SKIPPED",
                    detail="dry-run plan only — no network, no credentials loaded",
                )
            )
        report.notes.append(
            "dry-run: credentials were not read; no DNS/network used"
        )
        report.ended_at = now_iso()
        meta = write_report(report, output_dir) if output_dir else None
        return report, meta

    budget = Budget(
        max_requests=int(bud["max_requests"]),
        timeout_s=float(bud["timeout_s"]),
        deadline_s=float(bud["deadline_s"]),
        rate_rps=float(bud["rate_rps"]),
        max_body_bytes=cfg.max_body_bytes,
    )
    client = SafeHttpClient(
        origin,
        budget=budget,
        tls_verify=cfg.tls_verify,
        ca_file=cfg.tls_ca_file,
    )
    ctx = SuiteContext(
        client,
        cfg,
        profile,
        report.add,
        allow_fixture_writes=allow_fixture_writes,
        isolated_jwt_secret=isolated_jwt_secret,
    )
    for s in suite_list:
        runner = SUITE_RUNNERS.get(s)
        if not runner:
            raise ConfigError(f"unknown suite {s}")
        runner(ctx)

    seen = {c.check_id for c in report.checks}
    for req in required_check_ids(profile, suite_list):
        if req not in seen:
            suite = "X"
            if req.startswith("y."):
                suite = "Y"
            elif req.startswith("z."):
                suite = "Z"
            elif req.startswith("mqtt"):
                suite = "mqtt_acl"
            report.add(
                CheckResult(
                    check_id=req,
                    suite=suite,
                    title=f"missing:{req}",
                    status="BLOCKED",
                    detail="required check not produced by suite runner",
                )
            )

    report.executed = True
    report.dry_run = False
    report.budget["request_count"] = budget.request_count
    report.ended_at = now_iso()
    meta = write_report(report, output_dir) if output_dir else None
    return report, meta
