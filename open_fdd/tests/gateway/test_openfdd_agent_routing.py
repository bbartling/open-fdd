"""Tests for Open-FDD built-in agent SIMPLE/COMPLEX routing."""

from __future__ import annotations

from open_fdd.gateway.openfdd_agent_routing import classify_openfdd_task


def test_default_simple_when_vague() -> None:
    tier, reason = classify_openfdd_task("Please tidy my CSV headers for one site.")
    assert tier == "simple"
    assert "default" in reason.lower() or "simple" in reason.lower()


def test_simple_health_pattern() -> None:
    tier, reason = classify_openfdd_task("Call GET /health on the bridge and report JSON.")
    assert tier == "simple"
    assert "simple" in reason.lower()


def test_complex_multi_site() -> None:
    tier, reason = classify_openfdd_task("We need a multi-site BRICK import redesign across all campuses.")
    assert tier == "complex"
    assert "complex" in reason.lower()


def test_complex_security_keyword() -> None:
    tier, _ = classify_openfdd_task("Investigate a possible security vulnerability in our ingest path.")
    assert tier == "complex"


def test_force_complex_wins_over_simple_keyword() -> None:
    """If both could match, implementation prefers COMPLEX first."""
    tier, reason = classify_openfdd_task("security review of pass/fail gate for HTTP 500 on one endpoint")
    assert tier == "complex"
    assert "security" in reason.lower() or "complex" in reason.lower()
