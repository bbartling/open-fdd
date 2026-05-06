"""Resolve the OpenAI `codex` CLI on the host and run `login status` / `exec` (same pattern as a local Python harness)."""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Literal

# Defaults aligned with https://developers.openai.com/codex/models/ (override per host via env).
DEFAULT_CODEX_MODEL_SIMPLE = "gpt-5.4-mini"
DEFAULT_CODEX_MODEL_COMPLEX_PRIMARY = "gpt-5.5"
DEFAULT_CODEX_MODEL_COMPLEX_FALLBACK = "gpt-5.4"

TaskRoute = Literal["simple", "complex"]

_log = logging.getLogger(__name__)

_DEFAULT_SYSTEM = """You are a local coding assistant.

Rules:
- Answer the human's latest question directly.
- Be practical and concise.
- If the user asks for code changes, inspect the local workspace and make safe edits.
- When editing code, explain what changed and why.
"""


def _decode_completed(cp: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": int(cp.returncode),
        "stdout": (cp.stdout or "").strip(),
        "stderr": (cp.stderr or "").strip(),
    }


def safe_int_from_env(name: str, default: int) -> int:
    """Parse integer env vars; missing/blank/invalid values return ``default``."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip(), 10)
    except ValueError:
        return default


_VALID_SANDBOX_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})
_VALID_APPROVAL = frozenset({"never", "on-request", "untrusted"})


def _env_trim(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    s = str(raw).strip()
    return s if s else default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def describe_codex_exec_env() -> dict[str, Any]:
    """Summarize how the bridge will invoke ``codex exec`` (for diagnostics / operators)."""
    approval = _env_trim("OFDD_CODEX_EXEC_APPROVAL", "never").lower()
    if approval not in _VALID_APPROVAL:
        approval = "never"
    bypass = _env_bool("OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX", False)
    sandbox = _env_trim("OFDD_CODEX_EXEC_SANDBOX", "danger-full-access").lower()
    if sandbox not in _VALID_SANDBOX_MODES:
        sandbox = "danger-full-access"
    net = _env_bool("OFDD_CODEX_WORKSPACE_WRITE_NETWORK", True)
    if bypass:
        return {
            "ask_for_approval": approval,
            "sandbox_mode": "dangerously-bypass-approvals-and-sandbox",
            "workspace_write_network": None,
            "model_simple": _env_trim("OFDD_CODEX_MODEL_SIMPLE", DEFAULT_CODEX_MODEL_SIMPLE),
            "model_complex_primary": _env_trim("OFDD_CODEX_MODEL_COMPLEX", DEFAULT_CODEX_MODEL_COMPLEX_PRIMARY),
            "model_complex_fallback": _env_trim("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", DEFAULT_CODEX_MODEL_COMPLEX_FALLBACK),
            "llm_route_classify": _env_bool("OFDD_CODEX_LLM_CLASSIFY", False),
            "escalate_simple_failure_to_complex": _env_bool("OFDD_AGENT_ESCALATE_ON_FAILURE", True),
            "simple_tier_critic": _env_bool("OFDD_AGENT_SIMPLE_COMPLEX_CRITIC", True),
        }
    return {
        "ask_for_approval": approval,
        "sandbox_mode": sandbox,
        "workspace_write_network": net if sandbox == "workspace-write" else None,
        "model_simple": _env_trim("OFDD_CODEX_MODEL_SIMPLE", DEFAULT_CODEX_MODEL_SIMPLE),
        "model_complex_primary": _env_trim("OFDD_CODEX_MODEL_COMPLEX", DEFAULT_CODEX_MODEL_COMPLEX_PRIMARY),
        "model_complex_fallback": _env_trim("OFDD_CODEX_MODEL_COMPLEX_FALLBACK", DEFAULT_CODEX_MODEL_COMPLEX_FALLBACK),
        "llm_route_classify": _env_bool("OFDD_CODEX_LLM_CLASSIFY", False),
        "escalate_simple_failure_to_complex": _env_bool("OFDD_AGENT_ESCALATE_ON_FAILURE", True),
        "simple_tier_critic": _env_bool("OFDD_AGENT_SIMPLE_COMPLEX_CRITIC", True),
    }


def stderr_suggests_unknown_codex_model(stderr: str, stdout: str) -> bool:
    blob = f"{stderr}\n{stdout}".lower()
    needles = (
        "unknown model",
        "model not found",
        "invalid model",
        "is not available",
        "not a valid model",
        "unsupported model",
        "model_id",
        "does not have access",
    )
    return any(n in blob for n in needles)


def build_codex_exec_argv(codex_path: str, *, model: str | None = None) -> list[str]:
    """Build argv for non-interactive ``codex exec`` (global flags before the ``exec`` subcommand)."""
    approval = _env_trim("OFDD_CODEX_EXEC_APPROVAL", "never").lower()
    if approval not in _VALID_APPROVAL:
        approval = "never"
    cmd: list[str] = [codex_path, "--ask-for-approval", approval, "exec"]
    if _env_bool("OFDD_CODEX_DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX", False):
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        sandbox = _env_trim("OFDD_CODEX_EXEC_SANDBOX", "danger-full-access").lower()
        if sandbox not in _VALID_SANDBOX_MODES:
            sandbox = "danger-full-access"
        cmd.extend(["--sandbox", sandbox])
        if sandbox == "workspace-write" and _env_bool("OFDD_CODEX_WORKSPACE_WRITE_NETWORK", True):
            cmd.extend(["-c", "sandbox_workspace_write.network_access=true"])
    if model and str(model).strip():
        cmd.extend(["--model", str(model).strip()])
    cmd.extend(["--skip-git-repo-check", "--color", "never", "-"])
    return cmd


def run_npm_install_codex_global(*, timeout_s: int | None = None) -> dict[str, Any]:
    """Run ``npm install -g @openai/codex`` on the bridge host (operator-local desktop bridge)."""
    t = timeout_s if timeout_s is not None else safe_int_from_env("OFDD_NPM_INSTALL_CODEX_TIMEOUT_S", 600)
    t = max(60, min(t, 3600))
    try:
        cp = subprocess.run(
            ["npm", "install", "-g", "@openai/codex"],
            capture_output=True,
            text=True,
            timeout=t,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"npm install timed out after {t}s.",
        }
    except OSError as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"npm launch failed: {exc}",
        }
    out = _decode_completed(cp)
    out["ok"] = cp.returncode == 0
    return out


def resolve_codex_executable() -> str | None:
    """Return path to `codex` (Windows: often `codex.cmd` under npm global)."""
    override = (os.environ.get("OFDD_CODEX_CMD") or "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return str(p.resolve())
        _log.warning(
            "OFDD_CODEX_CMD is set but not found as a file (%r); falling back to shutil.which(\"codex\") "
            "and Windows where.exe lookup.",
            override,
        )

    w = shutil.which("codex")
    if w:
        return w

    if os.name == "nt":
        for arg in ("codex.cmd", "codex"):
            try:
                r = subprocess.run(
                    ["where.exe", arg],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    encoding="utf-8",
                    errors="replace",
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if r.returncode != 0 or not (r.stdout or "").strip():
                continue
            first = (r.stdout or "").strip().splitlines()[0].strip().strip('"')
            if first and Path(first).is_file():
                return str(Path(first).resolve())
    return None


def npm_global_prefix() -> str | None:
    try:
        r = subprocess.run(
            ["npm", "config", "get", "prefix"],
            capture_output=True,
            text=True,
            timeout=25,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    s = (r.stdout or "").strip()
    return s or None


def where_codex_lines() -> list[str]:
    """Windows `where.exe` lines for troubleshooting (empty on non-Windows or failure)."""
    if os.name != "nt":
        return []
    lines: list[str] = []
    for arg in ("codex.cmd", "codex"):
        try:
            r = subprocess.run(
                ["where.exe", arg],
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.stdout:
            lines.extend([ln.strip() for ln in r.stdout.splitlines() if ln.strip()])
    return lines


def codex_home_dir() -> Path:
    """Directory where the Codex CLI stores ``auth.json`` (``CODEX_HOME`` or ``~/.codex``)."""
    raw = (os.environ.get("CODEX_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


def _jwt_payload_dict(jwt: str) -> dict[str, Any] | None:
    parts = jwt.split(".")
    if len(parts) != 3:
        return None
    try:
        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        blob = base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8")
        parsed = json.loads(blob)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def chatgpt_account_id_from_access_jwt(access_token: str) -> str | None:
    """Best-effort ``account_id`` for Codex ``auth.json`` from the ChatGPT access JWT."""
    payload = _jwt_payload_dict(access_token)
    if not payload:
        return None
    auth_ns = payload.get("https://api.openai.com/auth")
    if isinstance(auth_ns, dict):
        aid = auth_ns.get("chatgpt_account_id")
        if isinstance(aid, str) and aid.strip():
            return aid.strip()
    return None


def persist_chatgpt_auth_from_device_tokens(
    access_token: str,
    refresh_token: str,
    *,
    id_token: str | None = None,
) -> dict[str, Any]:
    """Write ChatGPT OAuth tokens to ``auth.json`` so ``codex`` on this host can run after device login.

    Mirrors the shape described in OpenAI Codex auth docs (``auth_mode: chatgpt``, ``tokens``, ``last_refresh``).
    Does not return tokens to HTTP clients — callers should treat this as bridge-local persistence only.
    """
    access_token = (access_token or "").strip()
    refresh_token = (refresh_token or "").strip()
    if not access_token or not refresh_token:
        return {"ok": False, "error": "missing access_token or refresh_token"}

    home = codex_home_dir()
    try:
        home.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(home, 0o700)
    except OSError as exc:
        return {"ok": False, "error": f"cannot create CODEX_HOME {home}: {exc}"}

    auth_path = home / "auth.json"
    existing: dict[str, Any] | None = None
    if auth_path.is_file():
        try:
            raw_txt = auth_path.read_text(encoding="utf-8")
            parsed = json.loads(raw_txt)
            existing = parsed if isinstance(parsed, dict) else None
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"cannot read existing auth.json: {exc}"}

    if isinstance(existing, dict):
        mode = str(existing.get("auth_mode") or "").strip().lower()
        if mode == "api_key":
            return {"ok": False, "error": "refusing to overwrite API-key auth in auth.json; run codex logout first."}
        raw_key = existing.get("OPENAI_API_KEY")
        if isinstance(raw_key, str) and raw_key.strip():
            return {"ok": False, "error": "refusing to overwrite auth.json that contains OPENAI_API_KEY."}

    existing_tokens: dict[str, Any] = {}
    if isinstance(existing, dict) and isinstance(existing.get("tokens"), dict):
        existing_tokens = {str(k): v for k, v in existing["tokens"].items() if isinstance(k, str)}

    merged: dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    id_chosen = (id_token or "").strip() or ""
    if not id_chosen:
        old_id = existing_tokens.get("id_token")
        if isinstance(old_id, str) and old_id.strip():
            id_chosen = old_id.strip()
    if id_chosen:
        merged["id_token"] = id_chosen

    aid = chatgpt_account_id_from_access_jwt(access_token)
    if not aid:
        old_aid = existing_tokens.get("account_id")
        if isinstance(old_aid, str) and old_aid.strip():
            aid = old_aid.strip()
    if aid:
        merged["account_id"] = str(aid).strip()

    last_refresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    doc: dict[str, Any] = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": merged,
        "last_refresh": last_refresh,
    }

    tmp_path = Path(home) / f".auth.{os.getpid()}.tmp"
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        tmp_path.replace(auth_path)
    except OSError as exc:
        _log.warning("Failed to persist Codex auth.json under %s: %s", home, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": str(exc)}

    _log.info("Wrote ChatGPT OAuth tokens to %s", auth_path)
    return {"ok": True, "path": str(auth_path)}


def run_codex_login_status(codex_path: str) -> dict[str, Any]:
    try:
        cp = subprocess.run(
            [codex_path, "login", "status"],
            capture_output=True,
            text=True,
            timeout=90,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "codex login status timed out.", "logged_in": False}
    except OSError as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"codex spawn failed: {exc}",
            "logged_in": False,
        }
    out = _decode_completed(cp)
    out["logged_in"] = cp.returncode == 0
    return out


def run_codex_logout(codex_path: str) -> dict[str, Any]:
    """Run ``codex logout`` on the bridge host (clears stored ChatGPT / API credentials for that CLI)."""
    try:
        cp = subprocess.run(
            [codex_path, "logout"],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "codex logout timed out.",
        }
    except OSError as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"codex launch failed: {exc}",
        }
    out = _decode_completed(cp)
    out["ok"] = cp.returncode == 0
    return out


def run_codex_exec(
    codex_path: str,
    workdir: Path,
    *,
    stdin_text: str,
    timeout_s: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    t = timeout_s if timeout_s is not None else safe_int_from_env("OFDD_CODEX_EXEC_TIMEOUT_S", 600)
    t = max(30, min(t, 3600))
    try:
        cp = subprocess.run(
            build_codex_exec_argv(codex_path, model=model),
            cwd=str(workdir),
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=t,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"codex exec timed out after {t}s.",
            "ok": False,
        }
    except OSError as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"codex spawn failed: {exc}",
            "ok": False,
        }
    out = _decode_completed(cp)
    out["ok"] = cp.returncode == 0
    if model and str(model).strip():
        out["codex_model"] = str(model).strip()
    return out


_ROUTER_PROMPT = """You are a task router for an Open-FDD operator assistant.

Classify the following task summary as SIMPLE or COMPLEX:
- SIMPLE: one-shot checks (HTTP 200/404, /health), list endpoints, verify pass/fail, trivial one-liners.
- COMPLEX: code changes, design validation, multi-step debugging, BRICK/TTL/rules architecture, ambiguous root cause.

Reply with exactly one word on the first line: SIMPLE or COMPLEX. No punctuation, no explanation."""


def run_codex_route_classify_llm(
    codex_path: str,
    workdir: Path,
    *,
    task_summary: str,
    classify_model: str,
    timeout_s: int | None = None,
) -> tuple[TaskRoute | None, str]:
    """Optional second ``codex exec`` using the **simple** tier model to pick SIMPLE vs COMPLEX."""
    t = timeout_s if timeout_s is not None else safe_int_from_env("OFDD_CODEX_CLASSIFY_TIMEOUT_S", 120)
    t = max(20, min(t, 300))
    stdin_text = f"{_ROUTER_PROMPT}\n\n---\n{str(task_summary or '').strip()[:6000]}\n"
    out = run_codex_exec(codex_path, workdir, stdin_text=stdin_text, timeout_s=t, model=classify_model.strip())
    if not out.get("ok"):
        return None, f"classify_exec_failed: {out.get('stderr') or out.get('stdout') or 'unknown'}"
    raw = (out.get("stdout") or "").strip()
    first_line = raw.splitlines()[0].strip() if raw else ""
    first_word = first_line.split()[0].upper().strip(".,;:!\"'") if first_line else ""
    if first_word.startswith("COMPLEX"):
        return "complex", "llm_router"
    if first_word.startswith("SIMPLE"):
        return "simple", "llm_router"
    return None, f"classify_unparseable: {first_line!r}"


def _history_budget_chars() -> int:
    """
    Max UTF-8 length for the prior-turn markdown block.

    Uses ``OFDD_AGENT_CHAT_HISTORY_MAX_TOKENS`` (default 8000 ≈ 32k chars) capped by
    ``OFDD_AGENT_CHAT_HISTORY_MAX_CHARS`` so operators can hard-limit payload size.
    """
    max_tok = safe_int_from_env("OFDD_AGENT_CHAT_HISTORY_MAX_TOKENS", 8_000)
    max_tok = min(max(max_tok, 32), 200_000)
    cap_chars = safe_int_from_env("OFDD_AGENT_CHAT_HISTORY_MAX_CHARS", 120_000)
    cap_chars = min(max(cap_chars, 64), 500_000)
    return min(max_tok * 4, cap_chars)


def _markdown_history_block(
    entries: Sequence[tuple[str, str]],
    *,
    max_chars: int,
) -> tuple[str, bool]:
    """Format prior turns (oldest first) as markdown; keep the tail if over ``max_chars``."""
    chunks: list[str] = []
    size = 0
    truncated = False
    for role, text in reversed(entries):
        if role not in ("user", "assistant"):
            continue
        label = "Operator" if role == "user" else "Codex"
        chunk = f"**{label}:**\n{(text or '').strip()}\n\n"
        if size + len(chunk) > max_chars:
            truncated = True
            break
        chunks.append(chunk)
        size += len(chunk)
    body = "".join(reversed(chunks))
    if truncated:
        return f"_(Earlier messages omitted to stay within history limit.)_\n\n{body}", True
    return body, False


def build_chat_stdin(
    *,
    user_message: str,
    system_context: str | None,
    conversation_history: Sequence[tuple[str, str]] | None = None,
) -> str:
    system = (system_context or "").strip() or _DEFAULT_SYSTEM
    msg = user_message.strip()
    hist_raw = list(conversation_history or [])
    if not hist_raw:
        return f"{system}\n\nHuman message:\n{msg}\n\nRespond to the human message above.\n"
    # Cap prior-turn transcript by approximate tokens (see docs/howto/desktop_app.md).
    max_hist = _history_budget_chars()
    history_md, _trunc = _markdown_history_block(hist_raw, max_chars=max_hist)
    return (
        f"{system}\n\n### Conversation so far (same UI thread)\n\n{history_md}\n"
        f"### Latest human message\n{msg}\n\n"
        "Respond to the **latest** human message using the full thread above for continuity.\n"
    )


def gather_diagnostics() -> dict[str, Any]:
    codex = resolve_codex_executable()
    npm = npm_global_prefix()
    where_lines = where_codex_lines()
    hints: list[str] = []
    if not codex:
        hints.extend(
            [
                "Install CLI: npm install -g @openai/codex",
                "Find the binary: command -v codex   or   which codex",
                "npm global bin: npm config get prefix   (then look under bin/ or node_modules/.bin/)",
            ]
        )
        if os.name == "nt":
            hints.extend(
                [
                    "Windows: where.exe codex.cmd",
                    "Windows: where.exe codex",
                ]
            )
        hints.extend(
            [
                "Then in a terminal: codex login   or   codex login --device-auth",
                "If PATH is odd, set OFDD_CODEX_CMD to the full path to the codex executable.",
                "Check: codex login status",
            ]
        )
    login: dict[str, Any] | None = None
    if codex:
        login = run_codex_login_status(codex)
        if not login.get("logged_in"):
            hints.extend(["Run: codex login", "Or: codex login --device-auth", "Then: codex login status"])
    return {
        "codex_path": codex,
        "npm_prefix": npm,
        "where_codex": where_lines,
        "login_status": login,
        "hints": hints,
        "exec_env": describe_codex_exec_env(),
    }


def resolve_workdir(raw: str | None) -> Path:
    if raw and str(raw).strip():
        p = Path(str(raw).strip()).expanduser().resolve(strict=False)
    else:
        env = (os.environ.get("OFDD_CODEX_WORKDIR") or "").strip()
        p = Path(env).expanduser().resolve(strict=False) if env else Path.cwd().resolve()
    return p
