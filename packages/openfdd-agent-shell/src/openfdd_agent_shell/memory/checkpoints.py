from __future__ import annotations

from pathlib import Path

CHECKPOINTS_TEMPLATE = """# BUILD_CHECKPOINTS

Ordered mini queue for Codex wakes. Critique rewrites **Next for mini**; memory and divergence logs hold context.

## Last critique

_(none yet)_

## Current sprint

_(unset)_

## Next for mini (ordered)

1. Run `pytest open_fdd/tests/engine` and record the result in today's daily note.
2. Dry-run `openfdd-agent-shell --dry-run --message "scaffold the next manifest target"`.
3. Verify generated code stays under `workspace/`.

## Done recently

_(none yet)_
"""


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def ensure(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self.path.write_text(CHECKPOINTS_TEMPLATE, encoding="utf-8")
        return self.path

    def read(self) -> str:
        self.ensure()
        return self.path.read_text(encoding="utf-8")
