from __future__ import annotations

from pathlib import Path

from .cron.models import CronJob
from .manifest import Manifest
from .memory.store import MemoryPaths, MemoryStore


def _payload_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


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
    guardrails = manifest.repo_root / "skills" / "GUARDRAILS.md"
    if guardrails.is_file():
        blocks.extend(["", "## Skill guardrails", guardrails.read_text(encoding="utf-8").strip()])
    for skill_path in skill_paths(manifest.repo_root, manifest.agent_skills):
        blocks.append(f"\n## Skill: {skill_path.parent.name}\n")
        blocks.append(skill_path.read_text(encoding="utf-8").strip())
    return "\n".join(blocks).strip() + "\n"


def _repo_rel(manifest: Manifest, path: Path) -> str:
    try:
        return path.resolve().relative_to(manifest.repo_root).as_posix()
    except ValueError:
        return str(path)


def _wake_read_list(manifest: Manifest) -> list[str]:
    paths = MemoryPaths.from_manifest(manifest)
    items = [
        _repo_rel(manifest, manifest.repo_root / "AGENTS.md"),
        _repo_rel(manifest, manifest.manifest_path),
        _repo_rel(manifest, manifest.wake.bootstrap_snapshot),
        _repo_rel(manifest, manifest.wake.checkpoints_file),
        _repo_rel(manifest, paths.memory_root),
        _repo_rel(manifest, paths.architecture_readme),
        _repo_rel(manifest, paths.divergence_file),
        "skills/GUARDRAILS.md",
        "skills/workspace-memory/SKILL.md",
        "skills/workspace-cron/SKILL.md",
    ]
    return items


def build_mini_wake_message(
    manifest: Manifest,
    *,
    invocation: int,
    total: int,
    job_name: str = "",
) -> str:
    paths = MemoryPaths.from_manifest(manifest)
    arch_log = _repo_rel(manifest, paths.divergence_file)
    checkpoints = _repo_rel(manifest, manifest.wake.checkpoints_file)
    read_block = "\n".join(f"- {item}" for item in _wake_read_list(manifest))
    title = job_name or "open-fdd wake"
    return (
        f"Scheduled Open-FDD wake (mini {invocation}/{total}): {title}.\n\n"
        f"Read:\n{read_block}\n\n"
        "Rules:\n"
        f"- Do one small, reviewable slice toward **Next for mini** in {checkpoints} or open loops in MEMORY.md.\n"
        "- Write generated application code only under workspace/.\n"
        "- Run the narrowest verification you can (engine pytest, wheel smoke, or skill verification bullets).\n"
        "- Append a short bullet to today's workspace/memory/YYYY-MM-DD.md for what you verified or what failed.\n"
        f"- If working code or automation differs from skills or AGENTS.md because the documented path failed or was incomplete, append one dated block to {arch_log} (expectation, reality, evidence, status open). Do not duplicate the daily log.\n"
        "- Obey skills/GUARDRAILS.md before creating or editing skills/.\n"
        "- Stop after this slice."
    )


def build_critique_wake_message(manifest: Manifest, *, mini_count: int) -> str:
    memory = MemoryStore(manifest)
    open_count = memory.count_open_divergence_entries()
    paths = MemoryPaths.from_manifest(manifest)
    arch_log = _repo_rel(manifest, paths.divergence_file)
    checkpoints = _repo_rel(manifest, manifest.wake.checkpoints_file)
    read_block = "\n".join(f"- {item}" for item in _wake_read_list(manifest))
    return (
        f"Scheduled Open-FDD wake (critique after up to {mini_count} mini runs).\n\n"
        f"Read:\n{read_block}\n\n"
        "Tasks:\n"
        "1) Summarize what likely changed this wake (BUILD_CHECKPOINTS Done recently, daily notes, workspace diffs, cron run logs).\n"
        f"2) Rewrite {checkpoints}: **Last critique**, **Current sprint**, and replace **Next for mini** with 3-8 concrete tasks for the next wake.\n"
        "3) Promote stable facts into workspace/MEMORY.md; keep detailed session notes in daily files.\n"
        f"4) Architecture divergence: read {arch_log} ({open_count} open entries); triage new open entries; promote stable working patterns into skills/*/references/ or MEMORY.md; mark entries promoted or superseded.\n"
        "5) Skills: obey skills/GUARDRAILS.md; at most one material skill-folder change per wake unless maintenance is explicit.\n"
        "6) Be concise; optimize the next mini queue for clarity and safety."
    )


def build_codex_turn_message(manifest: Manifest, job: CronJob) -> str:
    payload = job.payload
    wake_mode = str(payload.get("wake_mode") or "").strip().lower()
    custom = str(payload.get("message") or "").strip()
    if wake_mode == "mini":
        return build_mini_wake_message(
            manifest,
            invocation=_payload_int(payload.get("invocation"), 1),
            total=_payload_int(payload.get("total"), manifest.wake.mini_invocations),
            job_name=job.name,
        )
    if wake_mode == "critique":
        return build_critique_wake_message(
            manifest,
            mini_count=_payload_int(payload.get("total"), manifest.wake.mini_invocations),
        )
    return custom or job.name
