from __future__ import annotations

from pathlib import Path

from .cron.models import CronJob
from .manifest import Manifest
from .memory.store import MemoryPaths, MemoryStore


def read_text_if_exists(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def skill_paths(repo_root: Path, skill_names: list[str]) -> list[Path]:
    paths: list[Path] = []
    for name in skill_names:
        skill_md = repo_root / "skills" / name / "SKILL.md"
        if skill_md.is_file():
            paths.append(skill_md)
    return paths


def build_system_prompt(manifest: Manifest) -> str:
    agents = read_text_if_exists(manifest.repo_root / "AGENTS.md")
    memory = MemoryStore(manifest)
    memory.ensure_layout()
    blocks = [
        "# Open-FDD agent session",
        f"Project: {manifest.project_name}",
        f"Workspace: {manifest.workspace_dir}",
        f"Scratch: {manifest.scratch_dir}",
        f"Engine: {manifest.engine_package} ({manifest.engine_install})",
        f"Build targets: {', '.join(manifest.build_targets) or '(none)'}",
        f"Drivers: {', '.join(manifest.build_drivers) or '(none)'}",
        f"Auth: {manifest.build_auth}",
        f"Deploy: {manifest.build_deploy}",
        "",
        "Write generated application code only under the workspace directory.",
        "Durable portfolio context lives in workspace/MEMORY.md and workspace/memory/.",
        "When working code under workspace/ diverges from skills or AGENTS.md, append to workspace/memory/architecture/working-divergence.md (not a second task queue).",
        "",
        memory.bootstrap_block(),
        "",
        agents.strip(),
    ]
    for skill_path in skill_paths(manifest.repo_root, manifest.agent_skills):
        blocks.append(f"\n## Skill: {skill_path.parent.name}\n")
        blocks.append(skill_path.read_text(encoding="utf-8").strip())
    return "\n".join(blocks).strip() + "\n"


def _repo_rel(manifest: Manifest, path: Path) -> str:
    try:
        return path.resolve().relative_to(manifest.repo_root).as_posix()
    except ValueError:
        return str(path)


def build_codex_turn_message(manifest: Manifest, job: CronJob) -> str:
    payload = job.payload
    wake_mode = str(payload.get("wake_mode") or "").strip().lower()
    custom = str(payload.get("message") or "").strip()
    if wake_mode not in {"mini", "critique"}:
        return custom or job.name

    paths = MemoryPaths.from_manifest(manifest)
    arch_readme = _repo_rel(manifest, paths.architecture_readme)
    arch_log = _repo_rel(manifest, paths.divergence_file)
    memory_root = _repo_rel(manifest, paths.memory_root)
    agents = _repo_rel(manifest, manifest.repo_root / "AGENTS.md")
    manifest_path = _repo_rel(manifest, manifest.manifest_path)

    read_list = [
        agents,
        manifest_path,
        memory_root,
        arch_readme,
        arch_log,
        "skills/workspace-memory/SKILL.md",
        "skills/workspace-cron/SKILL.md",
    ]
    read_block = "\n".join(f"- {item}" for item in read_list)

    if wake_mode == "mini":
        return (
            f"Scheduled Open-FDD wake (mini): {job.name}.\n\n"
            f"Read:\n{read_block}\n\n"
            "Rules:\n"
            "- Do one small, reviewable slice toward the operator goal in this job payload or open loops in MEMORY.md.\n"
            "- Write generated application code only under workspace/.\n"
            "- Append a short bullet to today's workspace/memory/YYYY-MM-DD.md for what you verified or what failed.\n"
            f"- If working code or automation differs from skills or AGENTS.md because the documented path failed or was incomplete, append one dated block to {arch_log} (expectation, reality, evidence, status open). Do not duplicate the daily log.\n"
            "- Stop after this slice."
        )

    return (
        f"Scheduled Open-FDD wake (critique): {job.name}.\n\n"
        f"Read:\n{read_block}\n\n"
        "Tasks:\n"
        "1) Summarize what likely changed since the last wake (daily notes, workspace diffs, cron run logs).\n"
        "2) Promote stable facts into workspace/MEMORY.md; keep detailed session notes in daily files.\n"
        f"3) Architecture divergence: read {arch_log}; triage new open entries; promote stable working patterns into skills/*/references/ or MEMORY.md; mark entries promoted or superseded.\n"
        "4) If skills need updates, change skills/ only when the operator manifest or an explicit maintenance task allows it.\n"
        "5) Be concise; optimize the next mini slice for clarity and safety."
    )
