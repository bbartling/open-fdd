"""Tests for `local_codex_cli` helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from open_fdd.gateway import local_codex_cli as lc


def test_run_npm_install_codex_global(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    out = lc.run_npm_install_codex_global(timeout_s=120)
    assert out["ok"] is True
    assert calls == [["npm", "install", "-g", "@openai/codex"]]


def test_run_npm_install_codex_global_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc.subprocess, "run", MagicMock(side_effect=FileNotFoundError("npm")))
    out = lc.run_npm_install_codex_global(timeout_s=120)
    assert out["ok"] is False
    assert out["returncode"] == -1
    assert "npm launch failed" in out["stderr"]


def test_run_codex_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="signed out\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    out = lc.run_codex_logout("/fake/codex")
    assert out["ok"] is True
    assert calls == [["/fake/codex", "logout"]]


def test_safe_int_from_env_invalid_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFDD_CODEX_EXEC_TIMEOUT_S", "not-a-number")
    captured: dict[str, object] = {}

    def fake_run(*_a: object, **k: object) -> MagicMock:
        captured.clear()
        captured.update(k)
        return MagicMock(returncode=0, stdout="out\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    lc.run_codex_exec("codex", tmp_path, stdin_text="prompt", timeout_s=None)
    assert captured["timeout"] == 600


def test_build_chat_stdin_includes_user_message() -> None:
    body = lc.build_chat_stdin(user_message="hello", system_context=None)
    assert "hello" in body
    assert "Human message:" in body


def test_build_chat_stdin_custom_system() -> None:
    body = lc.build_chat_stdin(user_message="x", system_context="SYS_ONLY")
    assert "SYS_ONLY" in body
    assert "x" in body


def test_build_chat_stdin_includes_conversation_history() -> None:
    hist = [("user", "first question"), ("assistant", "first answer")]
    body = lc.build_chat_stdin(
        user_message="follow up",
        system_context="SYS",
        conversation_history=hist,
    )
    assert "Conversation so far" in body
    assert "first question" in body
    assert "first answer" in body
    assert "follow up" in body
    assert "Latest human message" in body


def test_build_chat_stdin_history_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_AGENT_CHAT_HISTORY_MAX_TOKENS", "40")
    monkeypatch.setenv("OFDD_AGENT_CHAT_HISTORY_MAX_CHARS", "10_000_000")
    hist = [("user", "a" * 400), ("user", "tail")]
    body = lc.build_chat_stdin(user_message="z", system_context="S", conversation_history=hist)
    assert "tail" in body
    assert "z" in body
    assert "Earlier messages omitted" in body


def test_history_budget_chars_respects_token_and_char_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFDD_AGENT_CHAT_HISTORY_MAX_TOKENS", "10000")
    monkeypatch.setenv("OFDD_AGENT_CHAT_HISTORY_MAX_CHARS", "1000")
    assert lc._history_budget_chars() == 1000
    monkeypatch.setenv("OFDD_AGENT_CHAT_HISTORY_MAX_CHARS", "500000")
    assert lc._history_budget_chars() == 40_000


def test_resolve_workdir_blank_uses_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OFDD_CODEX_WORKDIR", raising=False)
    monkeypatch.chdir(tmp_path)
    wd = lc.resolve_workdir(None)
    assert wd == tmp_path.resolve()


def test_resolve_workdir_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OFDD_CODEX_WORKDIR", raising=False)
    d = tmp_path / "proj"
    d.mkdir()
    wd = lc.resolve_workdir(str(d))
    assert wd == d.resolve()


def test_gather_diagnostics_without_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OFDD_CODEX_EXEC_APPROVAL",
        "OFDD_CODEX_EXEC_SANDBOX",
        "OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX",
        "OFDD_CODEX_WORKSPACE_WRITE_NETWORK",
        "OFDD_CODEX_MODEL_SIMPLE",
        "OFDD_CODEX_MODEL_COMPLEX",
        "OFDD_CODEX_MODEL_COMPLEX_FALLBACK",
        "OFDD_CODEX_LLM_CLASSIFY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lc, "resolve_codex_executable", lambda: None)
    monkeypatch.setattr(lc, "npm_global_prefix", lambda: None)
    monkeypatch.setattr(lc, "where_codex_lines", lambda: [])
    out = lc.gather_diagnostics()
    assert out["codex_path"] is None
    assert any("npm install" in h.lower() for h in out["hints"])
    assert out["exec_env"]["ask_for_approval"] == "never"
    assert out["exec_env"]["sandbox_mode"] == "danger-full-access"
    assert out["exec_env"]["model_simple"] == "gpt-5.4-mini"
    assert out["exec_env"]["model_complex_primary"] == "gpt-5.5"


def test_gather_diagnostics_with_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OFDD_CODEX_EXEC_APPROVAL",
        "OFDD_CODEX_EXEC_SANDBOX",
        "OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX",
        "OFDD_CODEX_WORKSPACE_WRITE_NETWORK",
        "OFDD_CODEX_MODEL_SIMPLE",
        "OFDD_CODEX_MODEL_COMPLEX",
        "OFDD_CODEX_MODEL_COMPLEX_FALLBACK",
        "OFDD_CODEX_LLM_CLASSIFY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(lc, "resolve_codex_executable", lambda: "C:\\\\fake\\\\codex.cmd")
    monkeypatch.setattr(lc, "npm_global_prefix", lambda: "C:\\\\fake\\\\npm-prefix")
    monkeypatch.setattr(lc, "where_codex_lines", lambda: ["C:\\\\fake\\\\codex.cmd"])
    monkeypatch.setattr(
        lc,
        "run_codex_login_status",
        lambda _p: {"returncode": 0, "stdout": "ok", "stderr": "", "logged_in": True},
    )
    out = lc.gather_diagnostics()
    assert out["codex_path"] == "C:\\\\fake\\\\codex.cmd"
    assert out["npm_prefix"] == "C:\\\\fake\\\\npm-prefix"
    assert out["where_codex"] == ["C:\\\\fake\\\\codex.cmd"]
    assert out["login_status"]["logged_in"] is True
    assert out["exec_env"]["sandbox_mode"] == "danger-full-access"


def test_run_codex_exec_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="out\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    monkeypatch.delenv("OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX", raising=False)
    monkeypatch.delenv("OFDD_CODEX_EXEC_SANDBOX", raising=False)
    r = lc.run_codex_exec("codex", tmp_path, stdin_text="prompt")
    assert r["ok"] is True
    assert r["stdout"] == "out"
    assert calls[0][:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "--sandbox" in calls[0]
    assert calls[0][calls[0].index("--sandbox") + 1] == "danger-full-access"
    assert calls[0][-4:] == ["--skip-git-repo-check", "--color", "never", "-"]


def test_run_codex_exec_inserts_model_before_stdin_dash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    monkeypatch.delenv("OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX", raising=False)
    lc.run_codex_exec("codex", tmp_path, stdin_text="x", model="gpt-5.4-mini")
    assert "--model" in calls[0]
    mi = calls[0].index("--model")
    assert calls[0][mi + 1] == "gpt-5.4-mini"
    assert calls[0][-4:] == ["--skip-git-repo-check", "--color", "never", "-"]


def test_run_codex_exec_workspace_write_adds_network_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    monkeypatch.setenv("OFDD_CODEX_EXEC_SANDBOX", "workspace-write")
    monkeypatch.setenv("OFDD_CODEX_WORKSPACE_WRITE_NETWORK", "true")
    lc.run_codex_exec("codex", tmp_path, stdin_text="x")
    assert "-c" in calls[0]
    idx = calls[0].index("-c")
    assert calls[0][idx + 1] == "sandbox_workspace_write.network_access=true"


def test_run_codex_exec_bypass_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    monkeypatch.setenv("OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX", "1")
    lc.run_codex_exec("codex", tmp_path, stdin_text="x")
    assert "--dangerously-bypass-approvals-and-sandbox" in calls[0]
    assert "--sandbox" not in calls[0]


def test_run_codex_exec_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lc.subprocess, "run", MagicMock(side_effect=lc.subprocess.TimeoutExpired("codex", 1)))
    r = lc.run_codex_exec("codex", tmp_path, stdin_text="x", timeout_s=30)
    assert r["ok"] is False
    assert "timed out" in r["stderr"].lower()
