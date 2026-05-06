"""Tests for built-in Open-FDD agent (model routing + tier)."""

from __future__ import annotations

from pathlib import Path
import pytest

from open_fdd.gateway import openfdd_agent as agent


def test_openfdd_agent_simple_tier_uses_mini_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        calls.append(model)
        return {"returncode": 0, "stdout": "ok", "stderr": "", "ok": True, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.delenv("OFDD_CODEX_LLM_CLASSIFY", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    d = tmp_path / "w"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="ping /health",
        workdir_raw=str(d),
        task_summary="GET /health",
        force_class="simple",
        system_context=None,
    )
    assert out["ok"] is True
    assert calls == ["gpt-5.4-mini"]
    assert out.get("codex_model") == "gpt-5.4-mini"


def test_openfdd_agent_complex_retries_on_unknown_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        calls.append(model)
        if model == "gpt-5.5":
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "Error: unknown model gpt-5.5",
                "ok": False,
            }
        return {"returncode": 0, "stdout": "fixed", "stderr": "", "ok": True, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.delenv("OFDD_CODEX_LLM_CLASSIFY", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    d = tmp_path / "w2"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="do something",
        workdir_raw=str(d),
        task_summary="BRICK ttl import merge refactor",
        force_class="complex",
        system_context=None,
    )
    assert out["ok"] is True
    assert calls == ["gpt-5.5", "gpt-5.4"]
    assert out.get("codex_model_fallback_used") is True


def test_openfdd_agent_llm_classify_overrides_tier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main_models: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        main_models.append(model)
        return {"returncode": 0, "stdout": "done", "stderr": "", "ok": True, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "run_codex_route_classify_llm", lambda *_a, **_k: ("complex", "llm_router"))
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.setenv("OFDD_CODEX_LLM_CLASSIFY", "1")
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    d = tmp_path / "w3"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="GET /health",
        workdir_raw=str(d),
        task_summary="GET /health",
        force_class=None,
        system_context=None,
    )
    assert out["task_class"] == "complex"
    assert main_models == ["gpt-5.5"]


def test_openfdd_agent_escalates_to_complex_when_simple_codex_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        calls.append(model)
        if len(calls) == 1:
            return {"returncode": 9, "stdout": "", "stderr": "synthetic codex failure", "ok": False}
        return {"returncode": 0, "stdout": "recovered", "stderr": "", "ok": True, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.delenv("OFDD_CODEX_LLM_CLASSIFY", raising=False)
    monkeypatch.delenv("OFDD_AGENT_ROUTE_DEFAULT", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    monkeypatch.delenv("OFDD_AGENT_ESCALATE_ON_FAILURE", raising=False)
    d = tmp_path / "esc"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="ping something trivial",
        workdir_raw=str(d),
        task_summary="quick check please",
        force_class=None,
        system_context=None,
    )
    assert out["ok"] is True
    assert out["task_class"] == "complex"
    assert out.get("simple_failure_escalated") is True
    assert calls[0] == "gpt-5.4-mini" and calls[1] == "gpt-5.5"
    assert "escalated after SIMPLE codex failed" in str(out.get("route_reason"))


def test_openfdd_agent_human_requested_complex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        calls.append(model)
        return {"returncode": 0, "stdout": "ok", "stderr": "", "ok": True, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.delenv("OFDD_CODEX_LLM_CLASSIFY", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    d = tmp_path / "human"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="be thorough",
        workdir_raw=str(d),
        task_summary="anything",
        force_class=None,
        system_context=None,
        human_requested_complex=True,
    )
    assert out["task_class"] == "complex"
    assert out["route_reason"] == "human-requested COMPLEX evaluation"
    assert out.get("human_route") is True
    assert calls == ["gpt-5.5"]


def test_openfdd_agent_does_not_escalate_when_env_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        calls.append(model)
        return {"returncode": 1, "stdout": "", "stderr": "fail", "ok": False, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.delenv("OFDD_CODEX_LLM_CLASSIFY", raising=False)
    monkeypatch.setenv("OFDD_AGENT_ESCALATE_ON_FAILURE", "0")
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    d = tmp_path / "noesc"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="trivial ping",
        workdir_raw=str(d),
        task_summary="quick check",
        force_class=None,
        system_context=None,
    )
    assert out["ok"] is False
    assert out["task_class"] == "simple"
    assert calls == ["gpt-5.4-mini"]
    assert out.get("simple_failure_escalated") is None


def test_openfdd_agent_simple_smoke_response_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str | None] = []

    def fake_run(_c: str, _w: Path, *, stdin_text: str, timeout_s: int | None, model: str | None = None) -> dict:
        calls.append(model)
        return {"returncode": 0, "stdout": "simple response", "stderr": "", "ok": True, "codex_model": model}

    monkeypatch.setattr(agent, "run_codex_exec", fake_run)
    monkeypatch.setattr(agent, "resolve_codex_executable", lambda: "codex")
    monkeypatch.delenv("OFDD_AGENT_SIMPLE_COMPLEX_CRITIC", raising=False)
    monkeypatch.delenv("OFDD_CODEX_LLM_CLASSIFY", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_SIMPLE", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", raising=False)
    d = tmp_path / "critic"
    d.mkdir()
    out = agent.run_openfdd_agent_turn(
        message="quick help",
        workdir_raw=str(d),
        task_summary="quick help",
        force_class="simple",
        system_context=None,
    )
    assert out["ok"] is True
    assert out.get("task_class") == "simple"
    assert out.get("stdout") == "simple response"
    assert out.get("codex_model") == "gpt-5.4-mini"
    assert isinstance(out.get("route_reason"), str) and out["route_reason"]
    assert calls == ["gpt-5.4-mini"]
