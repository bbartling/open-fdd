from __future__ import annotations

import pytest

from open_fdd.gateway.openclaw_routing import classify_task, decide_route, load_route_policy


def test_classify_simple_http_failure() -> None:
    cls, reason = classify_task("HTTP 500 timeout from ingest endpoint")
    assert cls == "simple"
    assert "simple pattern" in reason


def test_classify_complex_security_issue() -> None:
    cls, reason = classify_task("Potential security vulnerability across components")
    assert cls == "complex"
    assert "complex pattern" in reason


def test_decide_route_uses_policy_agents() -> None:
    policy = load_route_policy()
    route = decide_route(policy=policy, task_summary="race condition when loads spike")
    assert route.task_class == "complex"
    assert route.agent_target.startswith("openclaw/")
    assert route.backend_model


def test_decide_route_can_select_lane_for_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_OPENCLAW_ROUTE_SIMPLE_LANES", "simple-a,simple-b")
    policy = load_route_policy()
    route = decide_route(policy=policy, task_summary="HTTP 500 timeout", site_id="site-123")
    assert route.task_class == "simple"
    assert route.agent_target in {"openclaw/simple-a", "openclaw/simple-b"}
    assert "site_id" in route.reason

