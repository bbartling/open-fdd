"""Call OpenClaw Gateway OpenAI-compatible chat completions (Codex via x-openclaw-model).

OAuth for ChatGPT/Codex stays inside OpenClaw; this client only uses the gateway
operator token (e.g. OPENCLAW_GATEWAY_TOKEN). See docs/open-fdd-claw-architecture.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from open_fdd.gateway.openclaw_routing import (
    TaskClass,
    decide_route,
    load_route_policy,
)


DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789"
DEFAULT_BACKEND_MODEL = "openai-codex/gpt-5.5"
OPENAI_AGENT_MODEL = "openclaw/default"


@dataclass(frozen=True)
class OpenClawChatResponse:
    """Minimal non-streaming chat completion result."""

    content: str
    raw: dict[str, Any]
    task_class: TaskClass | None = None
    route_reason: str | None = None


class OpenClawGatewayChatClient:
    """POST /v1/chat/completions on the OpenClaw gateway with bearer auth."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        gateway_token: str | None = None,
        backend_model: str | None = None,
        timeout_s: float = 120.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("OFDD_OPENCLAW_GATEWAY_URL") or DEFAULT_GATEWAY_URL).rstrip(
            "/"
        )
        if not base_url:
            self.base_url = (
                os.getenv("OFDD_CLAW_GATEWAY_URL")
                or os.getenv("OFDD_OPENCLAW_GATEWAY_URL")
                or DEFAULT_GATEWAY_URL
            ).rstrip("/")
        self.gateway_token = (
            gateway_token
            or os.getenv("OFDD_CLAW_GATEWAY_TOKEN")
            or os.getenv("OFDD_OPENCLAW_GATEWAY_TOKEN")
            or ""
        ).strip()
        self.backend_model = (
            backend_model
            or os.getenv("OFDD_CLAW_BACKEND_MODEL")
            or os.getenv("OFDD_OPENCLAW_BACKEND_MODEL")
            or DEFAULT_BACKEND_MODEL
        ).strip()
        self.timeout_s = timeout_s
        self._session = session or requests.Session()

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        user: str | None = None,
        temperature: float | None = None,
        model_target: str = OPENAI_AGENT_MODEL,
        backend_model: str | None = None,
        task_class: TaskClass | None = None,
        route_reason: str | None = None,
    ) -> OpenClawChatResponse:
        if not self.gateway_token:
            raise ValueError(
                "Missing gateway token: set OFDD_OPENCLAW_GATEWAY_TOKEN or pass gateway_token= "
                "(same secret as OFDD_CLAW_GATEWAY_TOKEN / OPENCLAW_GATEWAY_TOKEN / gateway.auth.token)."
            )
        if not messages:
            raise ValueError("messages must be a non-empty list of {role, content} dicts")

        url = urljoin(self.base_url + "/", "v1/chat/completions")
        body: dict[str, Any] = {
            "model": model_target,
            "messages": messages,
            "stream": False,
        }
        if user is not None:
            body["user"] = user
        if temperature is not None:
            body["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.gateway_token}",
            "Accept": "application/json",
            "x-openclaw-model": backend_model or self.backend_model,
        }

        resp = self._session.post(
            url, headers=headers, json=body, timeout=self.timeout_s
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"OpenClaw gateway chat failed HTTP {resp.status_code}: {resp.text[:2000]}"
            )

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            snippet = repr(data)[:2000]
            raise RuntimeError(f"OpenClaw gateway returned no choices: {snippet}")

        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if content is None:
            snippet = repr(data)[:2000]
            raise RuntimeError(f"OpenClaw gateway missing message.content: {snippet}")
        if not isinstance(content, str):
            content = str(content)

        return OpenClawChatResponse(
            content=content,
            raw=data,
            task_class=task_class,
            route_reason=route_reason,
        )

    def complete_for_task(
        self,
        *,
        task_summary: str,
        messages: list[dict[str, str]],
        user: str | None = None,
        temperature: float | None = None,
        forced_class: TaskClass | None = None,
        site_id: str | None = None,
    ) -> OpenClawChatResponse:
        policy = load_route_policy()
        route = decide_route(
            policy=policy, task_summary=task_summary, forced_class=forced_class, site_id=site_id
        )
        return self.complete(
            messages,
            user=user,
            temperature=temperature,
            model_target=route.agent_target,
            backend_model=route.backend_model,
            task_class=route.task_class,
            route_reason=route.reason,
        )
