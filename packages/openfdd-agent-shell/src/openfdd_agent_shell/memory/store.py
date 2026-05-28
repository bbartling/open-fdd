from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re

from ..manifest import Manifest

ARCHITECTURE_README = """# Working architecture vs skills/spec

Append-only log when **implemented** behavior under `workspace/` or automation **differs** from `skills/*/SKILL.md`, `AGENTS.md`, or operator manifest expectations because the documented path failed or was incomplete.

**File:** `working-divergence.md` (same folder).

**Mini:** append one dated block when you discover a durable mismatch during a slice.

**Critique:** triage open entries; promote stable patterns into `skills/*/references/` or `MEMORY.md`; mark entries `promoted` or `superseded` in the log.

Do not log secrets, credentials, or full skill pastes.
"""

DIVERGENCE_TEMPLATE = """# Working architecture divergence log

Append when live code or ops **work** but **skills/spec** are wrong, incomplete, or untested. Feeds skill improvements; not a second task queue.

## Entry template

```markdown
## YYYY-MM-DDTHH:MMZ — short title

- **Status:** open | promoted | superseded
- **Expectation (spec/skill):** path + one-line claim
- **Working reality:** what actually runs
- **Evidence:** paths, commands, smoke, logs
- **Skill/spec follow-up:** optional target file
```

*(No entries yet.)*
"""

MEMORY_TEMPLATE = """# Open-FDD workspace memory

Curated facts for this portfolio. Keep this file compact; put detailed daily notes under `memory/`.

## Client / portfolio

## Building systems

## Stack inventory

## Operator preferences

## Standing decisions

## Open loops
"""


@dataclass(frozen=True)
class MemoryPaths:
    workspace_dir: Path
    bootstrap_file: Path
    memory_root: Path
    architecture_dir: Path
    architecture_readme: Path
    divergence_file: Path

    @classmethod
    def from_manifest(cls, manifest: Manifest) -> MemoryPaths:
        cfg = manifest.memory
        architecture_dir = cfg.memory_root / "architecture"
        return cls(
            workspace_dir=manifest.workspace_dir,
            bootstrap_file=cfg.bootstrap_file,
            memory_root=cfg.memory_root,
            architecture_dir=architecture_dir,
            architecture_readme=architecture_dir / "README.md",
            divergence_file=architecture_dir / "working-divergence.md",
        )


def truncate_bootstrap(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    if max_chars <= 3:
        return ("." * max_chars, True)
    return text[: max_chars - 3].rstrip() + "...", True


class MemoryStore:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.paths = MemoryPaths.from_manifest(manifest)
        self.cfg = manifest.memory

    def ensure_layout(self) -> None:
        self.paths.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.paths.memory_root.mkdir(parents=True, exist_ok=True)
        for sub in ("sites", "clients", "engineers", "tools", "integrations", "architecture"):
            (self.paths.memory_root / sub).mkdir(parents=True, exist_ok=True)
        if not self.paths.bootstrap_file.is_file():
            self.paths.bootstrap_file.write_text(MEMORY_TEMPLATE, encoding="utf-8")
        if not self.paths.architecture_readme.is_file():
            self.paths.architecture_readme.write_text(ARCHITECTURE_README, encoding="utf-8")
        if not self.paths.divergence_file.is_file():
            self.paths.divergence_file.write_text(DIVERGENCE_TEMPLATE, encoding="utf-8")

    def read_bootstrap(self) -> str:
        self.ensure_layout()
        text = self.paths.bootstrap_file.read_text(encoding="utf-8")
        body, truncated = truncate_bootstrap(text, self.cfg.bootstrap_max_chars)
        if truncated:
            body += "\n\n_(MEMORY.md truncated for bootstrap; full file on disk.)_\n"
        return body

    def _daily_path(self, day: date) -> Path:
        return self.paths.memory_root / f"{day.isoformat()}.md"

    def read_daily_notes(self) -> str:
        self.ensure_layout()
        blocks: list[str] = []
        today = date.today()
        for offset in range(self.cfg.daily_lookback_days + 1):
            day = today - timedelta(days=offset)
            path = self._daily_path(day)
            if path.is_file():
                blocks.append(f"## Daily note {day.isoformat()}\n\n{path.read_text(encoding='utf-8').strip()}")
        return "\n\n".join(blocks).strip()

    def append_daily(self, line: str, *, day: date | None = None) -> Path:
        self.ensure_layout()
        target = day or date.today()
        path = self._daily_path(target)
        stamp = datetime.now().strftime("%H:%M")
        entry = f"- [{stamp}] {line.strip()}\n"
        if path.is_file():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(entry)
        else:
            path.write_text(f"# Daily note {target.isoformat()}\n\n{entry}", encoding="utf-8")
        return path

    def domain_path(self, category: str, entity_id: str) -> Path:
        cat = re.sub(r"[^a-zA-Z0-9._-]+", "-", category.strip()) or "default"
        if cat in {".", ".."} or "/" in category or "\\" in category:
            raise ValueError(f"invalid memory category: {category!r}")
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", entity_id.strip()) or "default"
        path = (self.paths.memory_root / cat / f"{safe}.md").resolve()
        root = self.paths.memory_root.resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"memory path escapes memory_root: {path}")
        return path

    def append_domain(self, category: str, entity_id: str, line: str) -> Path:
        self.ensure_layout()
        path = self.domain_path(category, entity_id)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{stamp}] {line.strip()}\n"
        if path.is_file():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(entry)
        else:
            path.write_text(f"# {category}/{entity_id}\n\n{entry}", encoding="utf-8")
        return path

    def remember(self, text: str) -> Path:
        return self.append_daily(f"remember: {text}")

    def search(self, query: str, *, limit: int = 20) -> list[tuple[Path, int, str]]:
        self.ensure_layout()
        needle = query.strip().lower()
        if not needle:
            return []
        hits: list[tuple[Path, int, str]] = []
        roots = [self.paths.bootstrap_file, self.paths.memory_root]
        for root in roots:
            if root.is_file():
                files = [root]
            else:
                files = sorted(root.rglob("*.md"))
            for path in files:
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for idx, line in enumerate(lines, start=1):
                    if needle in line.lower():
                        hits.append((path, idx, line.strip()))
                        if len(hits) >= limit:
                            return hits
        return hits

    def count_open_divergence_entries(self) -> int:
        self.ensure_layout()
        if not self.paths.divergence_file.is_file():
            return 0
        count = 0
        for line in self.paths.divergence_file.read_text(encoding="utf-8").splitlines():
            if "**Status:**" in line and "open" in line.lower():
                count += 1
        return count

    def write_bootstrap_snapshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.bootstrap_block(), encoding="utf-8")
        return path

    def read_divergence_log(self) -> str:
        self.ensure_layout()
        if not self.paths.divergence_file.is_file():
            return ""
        text = self.paths.divergence_file.read_text(encoding="utf-8").strip()
        body, truncated = truncate_bootstrap(text, self.cfg.divergence_max_chars)
        if truncated:
            body += "\n\n_(working-divergence.md truncated for bootstrap; full file on disk.)_\n"
        return body

    def bootstrap_block(self) -> str:
        parts = ["## Workspace memory (bootstrap)", self.read_bootstrap()]
        daily = self.read_daily_notes()
        if daily:
            parts.extend(["", "## Recent daily notes", daily])
        divergence = self.read_divergence_log()
        if divergence:
            parts.extend(["", "## Working architecture divergence", divergence])
        return "\n".join(parts).strip()
