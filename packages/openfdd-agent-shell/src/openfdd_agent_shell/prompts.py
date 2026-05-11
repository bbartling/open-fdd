from __future__ import annotations

from pathlib import Path

from .manifest import Manifest
from .memory.store import MemoryStore


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
        "",
        memory.bootstrap_block(),
        "",
        agents.strip(),
    ]
    for skill_path in skill_paths(manifest.repo_root, manifest.agent_skills):
        blocks.append(f"\n## Skill: {skill_path.parent.name}\n")
        blocks.append(skill_path.read_text(encoding="utf-8").strip())
    return "\n".join(blocks).strip() + "\n"
