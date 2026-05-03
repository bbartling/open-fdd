"""Tests for `local_codex_cli` helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from open_fdd.gateway import local_codex_cli as lc


def test_build_chat_stdin_includes_user_message() -> None:
    body = lc.build_chat_stdin(user_message="hello", system_context=None)
    assert "hello" in body
    assert "Human message:" in body


def test_build_chat_stdin_custom_system() -> None:
    body = lc.build_chat_stdin(user_message="x", system_context="SYS_ONLY")
    assert "SYS_ONLY" in body
    assert "x" in body


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
    monkeypatch.setattr(lc, "resolve_codex_executable", lambda: None)
    monkeypatch.setattr(lc, "npm_global_prefix", lambda: None)
    monkeypatch.setattr(lc, "where_codex_lines", lambda: [])
    out = lc.gather_diagnostics()
    assert out["codex_path"] is None
    assert any("npm install" in h.lower() for h in out["hints"])


def test_gather_diagnostics_with_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "resolve_codex_executable", lambda: "C:\\\\fake\\\\codex.cmd")
    monkeypatch.setattr(
        lc,
        "run_codex_login_status",
        lambda _p: {"returncode": 0, "stdout": "ok", "stderr": "", "logged_in": True},
    )
    out = lc.gather_diagnostics()
    assert out["codex_path"] == "C:\\\\fake\\\\codex.cmd"
    assert out["login_status"]["logged_in"] is True


def test_run_codex_exec_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = MagicMock(returncode=0, stdout="out\n", stderr="")
    monkeypatch.setattr(lc.subprocess, "run", lambda *a, **k: fake)
    r = lc.run_codex_exec("codex", tmp_path, stdin_text="prompt")
    assert r["ok"] is True
    assert r["stdout"] == "out"


def test_run_codex_exec_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(lc.subprocess, "run", MagicMock(side_effect=lc.subprocess.TimeoutExpired("codex", 1)))
    r = lc.run_codex_exec("codex", tmp_path, stdin_text="x", timeout_s=30)
    assert r["ok"] is False
    assert "timed out" in r["stderr"].lower()
