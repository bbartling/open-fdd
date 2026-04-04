from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
E2E_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT_DIR = Path(r"C:\Users\ben\OneDrive\Desktop\testing\automated_testing\reports")
DEFAULT_ENV = Path(r"C:\Users\ben\OneDrive\Desktop\BensOpenClawTesting\.env")


@dataclass
class StepResult:
    name: str
    command: list[str]
    returncode: int
    started_at: str
    finished_at: str
    duration_sec: float
    log_path: str
    stdout_tail: str
    stderr_tail: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _tail(text: str, lines: int = 80, chars: int = 6000) -> str:
    parts = text.splitlines()
    text2 = "\n".join(parts[-lines:])
    return text2[-chars:]


def _load_env_file(env_path: Path) -> dict[str, str]:
    env_updates: dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path}")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env_updates[k.strip()] = v.strip()
    return env_updates


def _run_step(name: str, command: Sequence[str], env: dict[str, str], report_dir: Path) -> StepResult:
    started = _utc_now()
    proc = subprocess.run(
        list(command),
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    finished = _utc_now()
    duration = (finished - started).total_seconds()
    safe_name = name.lower().replace(" ", "_").replace("/", "-")
    log_path = report_dir / f"one_pass_{safe_name}.log"
    log_path.write_text(
        f"# COMMAND\n{' '.join(command)}\n\n# RETURN CODE\n{proc.returncode}\n\n# STDOUT\n{proc.stdout}\n\n# STDERR\n{proc.stderr}\n",
        encoding="utf-8",
    )
    return StepResult(
        name=name,
        command=list(command),
        returncode=proc.returncode,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_sec=duration,
        log_path=str(log_path),
        stdout_tail=_tail(proc.stdout),
        stderr_tail=_tail(proc.stderr),
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    api_url = "http://192.168.204.16:8000"
    frontend_url = "http://192.168.204.16"
    bacnet_url = "http://192.168.204.16:8080"
    env_path = DEFAULT_ENV
    report_dir = DEFAULT_REPORT_DIR
    ignore_ssl = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--api-url" and i + 1 < len(argv):
            api_url = argv[i + 1]
            i += 2
            continue
        if arg == "--frontend-url" and i + 1 < len(argv):
            frontend_url = argv[i + 1]
            i += 2
            continue
        if arg == "--bacnet-url" and i + 1 < len(argv):
            bacnet_url = argv[i + 1]
            i += 2
            continue
        if arg == "--env-file" and i + 1 < len(argv):
            env_path = Path(argv[i + 1])
            i += 2
            continue
        if arg == "--report-dir" and i + 1 < len(argv):
            report_dir = Path(argv[i + 1])
            i += 2
            continue
        if arg == "--ignore-ssl":
            ignore_ssl = True
            i += 1
            continue
        raise SystemExit(f"Unknown or incomplete arg: {arg}")

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = report_dir / f"one_pass_bundle_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["OPENCLAW_STACK_ENV"] = str(env_path)
    env.pop("OFDD_API_KEY", None)
    env_updates = _load_env_file(env_path)
    env.update(env_updates)

    ssl_args: list[str] = ["--ignore-ssl"] if ignore_ssl else []

    steps: list[tuple[str, list[str]]] = [
        (
            "frontend_smoke",
            [
                sys.executable,
                str(E2E_DIR / "1_e2e_frontend_selenium.py"),
                "--frontend-url",
                frontend_url,
                *ssl_args,
                "--bacnet-device-instance",
                "3456789",
                "3456790",
            ],
        ),
        (
            "sparql_frontend_parity",
            [
                sys.executable,
                str(E2E_DIR / "2_sparql_crud_and_frontend_test.py"),
                "--api-url",
                api_url,
                "--frontend-url",
                frontend_url,
                *ssl_args,
                "--frontend-parity",
                "--save-report",
                str(run_dir / "sparql_crud_report.json"),
            ],
        ),
        (
            "hot_reload_frontend",
            [
                sys.executable,
                str(E2E_DIR / "4_hot_reload_test.py"),
                "--api-url",
                api_url,
                "--frontend-url",
                frontend_url,
                *ssl_args,
                "--frontend-check",
            ],
        ),
        (
            "ai_modeling_pass",
            [
                sys.executable,
                str(E2E_DIR / "ai_modeling_pass.py"),
            ],
        ),
    ]

    results: list[StepResult] = []
    for name, command in steps:
        print(f"\n=== RUNNING {name} ===")
        result = _run_step(name, command, env, run_dir)
        results.append(result)
        print(f"{name}: returncode={result.returncode} log={result.log_path}")

    summary = {
        "started_local": stamp,
        "repo_root": str(REPO_ROOT),
        "env_file": str(env_path),
        "api_url": api_url,
        "frontend_url": frontend_url,
        "bacnet_url": bacnet_url,
        "steps": [asdict(r) for r in results],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        f"# One-pass bundle {stamp}",
        "",
        f"- env file: `{env_path}`",
        f"- api url: `{api_url}`",
        f"- frontend url: `{frontend_url}`",
        f"- bacnet url: `{bacnet_url}`",
        "",
        "## Step summary",
        "",
    ]
    for r in results:
        status = "PASS" if r.returncode == 0 else "FAIL"
        lines += [
            f"### {r.name} — {status}",
            f"- return code: `{r.returncode}`",
            f"- duration_sec: `{r.duration_sec:.1f}`",
            f"- log: `{r.log_path}`",
            "- command:",
            "```text",
            " ".join(r.command),
            "```",
            "- stdout tail:",
            "```text",
            r.stdout_tail or "<empty>",
            "```",
            "- stderr tail:",
            "```text",
            r.stderr_tail or "<empty>",
            "```",
            "",
        ]
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    failing = [r for r in results if r.returncode != 0]
    print(f"\nBundle written to: {run_dir}")
    print(f"Summary markdown: {run_dir / 'summary.md'}")
    print(f"Summary json: {run_dir / 'summary.json'}")
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
