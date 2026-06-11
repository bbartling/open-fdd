from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.prompts import build_system_prompt, skill_paths


def test_build_system_prompt_includes_agents_and_skills(repo_root):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", repo_root)
    prompt = build_system_prompt(manifest)
    assert "Open-FDD agent session" in prompt
    assert "openfdd-mcp-server" in prompt
    assert "engine-first" in prompt.lower()
    assert "Workspace memory" in prompt


def test_skill_paths_resolves_existing_skills(repo_root):
    paths = skill_paths(repo_root, ["openfdd-mcp-server", "missing-skill"])
    assert len(paths) == 1
    assert paths[0].name == "SKILL.md"
