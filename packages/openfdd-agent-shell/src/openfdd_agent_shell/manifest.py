from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


@dataclass
class CronConfig:
    jobs_file: Path
    state_file: Path
    runs_dir: Path
    timezone: str


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

    @classmethod
    def load(cls, manifest_path: Path, repo_root: Path) -> Manifest:
        raw = _load_toml(manifest_path)
        project = raw.get("project") or {}
        engine = raw.get("engine") or {}
        build = raw.get("build") or {}
        agent = raw.get("agent") or {}
        memory_raw = raw.get("memory") or {}
        cron_raw = raw.get("cron") or {}

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
        scratch_dir = (repo_root / scratch_rel).resolve()

        bootstrap_rel = str(memory_raw.get("bootstrap_file") or "workspace/MEMORY.md").strip()
        memory_root_rel = str(memory_raw.get("root") or "workspace/memory").strip()
        bootstrap_max_chars = int(memory_raw.get("bootstrap_max_chars") or 12000)
        daily_lookback_days = int(memory_raw.get("daily_lookback_days") or 2)

        jobs_rel = str(cron_raw.get("jobs_file") or "workspace/cron/jobs.json").strip()
        state_rel = str(cron_raw.get("state_file") or "workspace/cron/jobs-state.json").strip()
        runs_rel = str(cron_raw.get("runs_dir") or "workspace/cron/runs").strip()
        timezone = str(cron_raw.get("timezone") or "UTC").strip()

        memory = MemoryConfig(
            bootstrap_file=(repo_root / bootstrap_rel).resolve(),
            memory_root=(repo_root / memory_root_rel).resolve(),
            bootstrap_max_chars=bootstrap_max_chars,
            daily_lookback_days=daily_lookback_days,
        )
        cron = CronConfig(
            jobs_file=(repo_root / jobs_rel).resolve(),
            state_file=(repo_root / state_rel).resolve(),
            runs_dir=(repo_root / runs_rel).resolve(),
            timezone=timezone,
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
        )

    def ensure_workspace_dirs(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.memory.memory_root.mkdir(parents=True, exist_ok=True)
        self.cron.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        self.cron.runs_dir.mkdir(parents=True, exist_ok=True)
