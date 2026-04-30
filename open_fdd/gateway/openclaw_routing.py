"""Task routing policy for OpenClaw simple vs complex lanes."""

from __future__ import annotations

import os
import re
import zlib
from dataclasses import dataclass
from typing import Literal

TaskClass = Literal["simple", "complex"]


@dataclass(frozen=True)
class OpenClawRouteDecision:
    task_class: TaskClass
    agent_target: str
    backend_model: str
    reason: str


@dataclass(frozen=True)
class OpenClawRoutePolicy:
    simple_agent_id: str
    complex_agent_id: str
    simple_backend_model: str
    complex_backend_model: str
    default_class: TaskClass
    strict_mode: bool
    simple_lane_agents: tuple[str, ...]
    complex_lane_agents: tuple[str, ...]


DEFAULT_SIMPLE_BACKEND = "openai-codex/gpt-5.5"
DEFAULT_COMPLEX_BACKEND = "openai-codex/gpt-5.5"

_COMPLEX_PATTERNS = [
    r"\brace condition\b",
    r"\btiming[- ]dependent\b",
    r"\bsecurity\b",
    r"\bvulnerab",
    r"\bperformance\b",
    r"\bdegradation\b",
    r"\bspans?\b.{0,20}\b(component|file|service)",
    r"\bambiguous\b",
    r"\broot cause\b",
]

_SIMPLE_PATTERNS = [
    r"\bpass/fail\b",
    r"\bhttp\b.{0,20}\b(404|500|timeout)\b",
    r"\bmissing\b.{0,20}\b(ui|selector|element)\b",
    r"\bsetup failure\b",
    r"\bsyntax error\b",
    r"\bimport failure\b",
]


def load_route_policy() -> OpenClawRoutePolicy:
    simple_agent = (
        os.getenv("OFDD_CLAW_ROUTE_SIMPLE_AGENT")
        or os.getenv("OFDD_OPENCLAW_ROUTE_SIMPLE_AGENT")
        or "simple"
    ).strip() or "simple"
    complex_agent = (
        os.getenv("OFDD_CLAW_ROUTE_COMPLEX_AGENT")
        or os.getenv("OFDD_OPENCLAW_ROUTE_COMPLEX_AGENT")
        or "complex"
    ).strip() or "complex"
    simple_backend = (
        os.getenv("OFDD_CLAW_ROUTE_SIMPLE_BACKEND_MODEL")
        or os.getenv("OFDD_OPENCLAW_ROUTE_SIMPLE_BACKEND_MODEL")
        or DEFAULT_SIMPLE_BACKEND
    ).strip() or DEFAULT_SIMPLE_BACKEND
    complex_backend = (
        os.getenv("OFDD_CLAW_ROUTE_COMPLEX_BACKEND_MODEL")
        or os.getenv("OFDD_OPENCLAW_ROUTE_COMPLEX_BACKEND_MODEL")
        or DEFAULT_COMPLEX_BACKEND
    ).strip() or DEFAULT_COMPLEX_BACKEND
    default_class_raw = (
        os.getenv("OFDD_CLAW_ROUTE_DEFAULT_CLASS")
        or os.getenv("OFDD_OPENCLAW_ROUTE_DEFAULT_CLASS")
        or "simple"
    ).strip().lower()
    default_class: TaskClass = "complex" if default_class_raw == "complex" else "simple"
    strict_raw = (
        os.getenv("OFDD_CLAW_ROUTE_STRICT_MODE")
        or os.getenv("OFDD_OPENCLAW_ROUTE_STRICT_MODE")
        or "true"
    ).strip().lower()
    strict_mode = strict_raw in {"1", "true", "yes", "on"}
    simple_lanes = tuple(
        x.strip()
        for x in (
            os.getenv("OFDD_CLAW_ROUTE_SIMPLE_LANES")
            or os.getenv("OFDD_OPENCLAW_ROUTE_SIMPLE_LANES")
            or ""
        ).split(",")
        if x.strip()
    )
    complex_lanes = tuple(
        x.strip()
        for x in (
            os.getenv("OFDD_CLAW_ROUTE_COMPLEX_LANES")
            or os.getenv("OFDD_OPENCLAW_ROUTE_COMPLEX_LANES")
            or ""
        ).split(",")
        if x.strip()
    )
    return OpenClawRoutePolicy(
        simple_agent_id=simple_agent,
        complex_agent_id=complex_agent,
        simple_backend_model=simple_backend,
        complex_backend_model=complex_backend,
        default_class=default_class,
        strict_mode=strict_mode,
        simple_lane_agents=simple_lanes,
        complex_lane_agents=complex_lanes,
    )


def classify_task(task_summary: str, *, default_class: TaskClass = "simple") -> tuple[TaskClass, str]:
    text = str(task_summary or "").strip().lower()
    if not text:
        return default_class, "empty summary -> default class"
    for pattern in _COMPLEX_PATTERNS:
        if re.search(pattern, text):
            return "complex", f"matched complex pattern: {pattern}"
    for pattern in _SIMPLE_PATTERNS:
        if re.search(pattern, text):
            return "simple", f"matched simple pattern: {pattern}"
    return default_class, "no specific pattern -> default class"


def decide_route(
    *,
    policy: OpenClawRoutePolicy,
    task_summary: str,
    forced_class: TaskClass | None = None,
    site_id: str | None = None,
) -> OpenClawRouteDecision:
    if forced_class is not None:
        task_class: TaskClass = forced_class
        reason = "forced class override"
    else:
        task_class, reason = classify_task(task_summary, default_class=policy.default_class)
    if task_class == "complex":
        complex_target = _pick_lane_target(policy.complex_agent_id, policy.complex_lane_agents, site_id)
        return OpenClawRouteDecision(
            task_class=task_class,
            agent_target=f"openclaw/{complex_target}",
            backend_model=policy.complex_backend_model,
            reason=_with_lane_reason(reason, site_id, complex_target),
        )
    simple_target = _pick_lane_target(policy.simple_agent_id, policy.simple_lane_agents, site_id)
    return OpenClawRouteDecision(
        task_class=task_class,
        agent_target=f"openclaw/{simple_target}",
        backend_model=policy.simple_backend_model,
        reason=_with_lane_reason(reason, site_id, simple_target),
    )


def _pick_lane_target(default_agent: str, lanes: tuple[str, ...], site_id: str | None) -> str:
    if not lanes:
        return default_agent
    key = str(site_id or "").strip()
    if not key:
        return lanes[0]
    idx = zlib.crc32(key.encode("utf-8")) % len(lanes)
    return lanes[idx]


def _with_lane_reason(reason: str, site_id: str | None, target: str) -> str:
    if str(site_id or "").strip():
        return f"{reason}; lane selected for site_id -> {target}"
    return f"{reason}; default lane -> {target}"

