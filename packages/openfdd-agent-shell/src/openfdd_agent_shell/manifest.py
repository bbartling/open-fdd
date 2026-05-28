from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _resolve_under_workspace(
    repo_root: Path,
    workspace_dir: Path,
    rel: str,
    *,
    label: str,
) -> Path:
    resolved = (repo_root / rel).resolve()
    workspace = workspace_dir.resolve()
    if workspace not in resolved.parents and resolved != workspace:
        raise ValueError(
            f"{label} must resolve under workspace_dir ({workspace}), got {resolved}"
        )
    return resolved


def _load_toml(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(data.decode("utf-8"))
    import tomli

    return tomli.loads(data.decode("utf-8"))


@dataclass
class MemoryConfig:
    bootstrap_file: Path
    memory_root: Path
    bootstrap_max_chars: int
    daily_lookback_days: int
    divergence_max_chars: int


@dataclass
class CronConfig:
    jobs_file: Path
    state_file: Path
    runs_dir: Path
    timezone: str


@dataclass
class WakeConfig:
    mini_invocations: int
    min_minutes_between: int
    mini_model: str | None
    critique_model: str | None
    lock_file: Path
    debounce_file: Path
    stop_early_file: Path
    wakes_dir: Path
    checkpoints_file: Path
    bootstrap_snapshot: Path


@dataclass
class Manifest:
    project_name: str
    workspace_dir: Path
    engine_install: str
    engine_package: str
    build_targets: list[str]
    build_drivers: list[str]
    build_auth: str
    build_deploy: str
    agent_skills: list[str]
    codex_bin: str
    scratch_dir: Path
    repo_root: Path
    manifest_path: Path
    memory: MemoryConfig
    cron: CronConfig
    wake: WakeConfig

    @classmethod
    def load(cls, manifest_path: Path, repo_root: Path) -> Manifest:
        raw = _load_toml(manifest_path)
        project = raw.get("project") or {}
        engine = raw.get("engine") or {}
        build = raw.get("build") or {}
        agent = raw.get("agent") or {}
        memory_raw = raw.get("memory") or {}
        cron_raw = raw.get("cron") or {}
        wake_raw = raw.get("wake") or {}

        name = str(project.get("name") or "open-fdd-workspace").strip()
        workspace_rel = str(project.get("workspace_dir") or "workspace").strip()
        workspace_dir = (repo_root / workspace_rel).resolve()

        engine_install = str(engine.get("install") or "pypi").strip().lower()
        if engine_install not in {"pypi", "editable"}:
            raise ValueError("engine.install must be 'pypi' or 'editable'")

        engine_package = str(engine.get("package") or "open-fdd").strip()
        targets = [str(x) for x in (build.get("targets") or [])]
        drivers = [str(x) for x in (build.get("drivers") or [])]
        auth = str(build.get("auth") or "none").strip().lower()
        deploy = str(build.get("deploy") or "local").strip().lower()

        skills = [str(x) for x in (agent.get("skills") or [])]
        codex_bin = str(agent.get("codex_bin") or "codex").strip()
        scratch_rel = str(agent.get("scratch_dir") or "workspace/scratch").strip()
        scratch_dir = _resolve_under_workspace(
            repo_root, workspace_dir, scratch_rel, label="agent.scratch_dir"
        )

        bootstrap_rel = str(memory_raw.get("bootstrap_file") or "workspace/MEMORY.md").strip()
        memory_root_rel = str(memory_raw.get("root") or "workspace/memory").strip()
        bootstrap_max_chars = int(memory_raw.get("bootstrap_max_chars") or 12000)
        daily_lookback_days = int(memory_raw.get("daily_lookback_days") or 2)
        divergence_max_chars = int(memory_raw.get("divergence_max_chars") or 4000)

        jobs_rel = str(cron_raw.get("jobs_file") or "workspace/cron/jobs.json").strip()
        state_rel = str(cron_raw.get("state_file") or "workspace/cron/jobs-state.json").strip()
        runs_rel = str(cron_raw.get("runs_dir") or "workspace/cron/runs").strip()
        timezone = str(cron_raw.get("timezone") or "UTC").strip()

        mini_invocations = int(wake_raw.get("mini_invocations") or 2)
        min_minutes_between = int(wake_raw.get("min_minutes_between") or 0)
        mini_model = wake_raw.get("mini_model")
        critique_model = wake_raw.get("critique_model")
        lock_rel = str(wake_raw.get("lock_file") or "workspace/cron/wake.lock").strip()
        debounce_rel = str(wake_raw.get("debounce_file") or "workspace/cron/last_wake_epoch").strip()
        stop_early_rel = str(wake_raw.get("stop_early_file") or "workspace/cron/stop_mini_loop").strip()
        wakes_rel = str(wake_raw.get("wakes_dir") or "workspace/cron/wakes").strip()
        checkpoints_rel = str(
            wake_raw.get("checkpoints_file") or "workspace/BUILD_CHECKPOINTS.md"
        ).strip()
        snapshot_rel = str(
            wake_raw.get("bootstrap_snapshot") or "workspace/scratch/memory-bootstrap-latest.md"
        ).strip()

        memory = MemoryConfig(
            bootstrap_file=_resolve_under_workspace(
                repo_root, workspace_dir, bootstrap_rel, label="memory.bootstrap_file"
            ),
            memory_root=_resolve_under_workspace(
                repo_root, workspace_dir, memory_root_rel, label="memory.root"
            ),
            bootstrap_max_chars=bootstrap_max_chars,
            daily_lookback_days=daily_lookback_days,
            divergence_max_chars=divergence_max_chars,
        )
        cron = CronConfig(
            jobs_file=_resolve_under_workspace(
                repo_root, workspace_dir, jobs_rel, label="cron.jobs_file"
            ),
            state_file=_resolve_under_workspace(
                repo_root, workspace_dir, state_rel, label="cron.state_file"
            ),
            runs_dir=_resolve_under_workspace(
                repo_root, workspace_dir, runs_rel, label="cron.runs_dir"
            ),
            timezone=timezone,
        )
        wake = WakeConfig(
            mini_invocations=mini_invocations,
            min_minutes_between=min_minutes_between,
            mini_model=str(mini_model).strip() if mini_model else None,
            critique_model=str(critique_model).strip() if critique_model else None,
            lock_file=_resolve_under_workspace(
                repo_root, workspace_dir, lock_rel, label="wake.lock_file"
            ),
            debounce_file=_resolve_under_workspace(
                repo_root, workspace_dir, debounce_rel, label="wake.debounce_file"
            ),
            stop_early_file=_resolve_under_workspace(
                repo_root, workspace_dir, stop_early_rel, label="wake.stop_early_file"
            ),
            wakes_dir=_resolve_under_workspace(
                repo_root, workspace_dir, wakes_rel, label="wake.wakes_dir"
            ),
            checkpoints_file=_resolve_under_workspace(
                repo_root, workspace_dir, checkpoints_rel, label="wake.checkpoints_file"
            ),
            bootstrap_snapshot=_resolve_under_workspace(
                repo_root, workspace_dir, snapshot_rel, label="wake.bootstrap_snapshot"
            ),
        )

        return cls(
            project_name=name,
            workspace_dir=workspace_dir,
            engine_install=engine_install,
            engine_package=engine_package,
            build_targets=targets,
            build_drivers=drivers,
            build_auth=auth,
            build_deploy=deploy,
            agent_skills=skills,
            codex_bin=codex_bin,
            scratch_dir=scratch_dir,
            repo_root=repo_root.resolve(),
            manifest_path=manifest_path.resolve(),
            memory=memory,
            cron=cron,
            wake=wake,
        )

    def ensure_workspace_dirs(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.memory.memory_root.mkdir(parents=True, exist_ok=True)
        self.cron.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        self.cron.runs_dir.mkdir(parents=True, exist_ok=True)
        self.wake.wakes_dir.mkdir(parents=True, exist_ok=True)
        self.wake.checkpoints_file.parent.mkdir(parents=True, exist_ok=True)
        self.wake.bootstrap_snapshot.parent.mkdir(parents=True, exist_ok=True)
