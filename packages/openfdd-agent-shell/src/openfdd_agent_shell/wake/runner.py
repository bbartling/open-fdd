from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from pathlib import Path

from ..codex_launcher import build_invocation, codex_available, dry_run_command, run_invocation
from ..manifest import Manifest
from ..memory.checkpoints import CheckpointStore
from ..memory.store import MemoryStore
from ..prompts import build_critique_wake_message, build_mini_wake_message
from .lock import WakeLockError, wake_lock


@dataclass
class WakeRunResult:
    log_path: Path
    mini_runs: int
    critique_ran: bool
    dry_run: bool
    debounced: bool
    locked: bool


class WakeRunner:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.memory = MemoryStore(manifest)
        self.checkpoints = CheckpointStore(manifest.wake.checkpoints_file)

    def _debounced(self) -> bool:
        minutes = self.manifest.wake.min_minutes_between
        if minutes <= 0 or not self.manifest.wake.debounce_file.is_file():
            return False
        try:
            last = float(self.manifest.wake.debounce_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return False
        return (time.time() - last) < minutes * 60

    def _stamp_debounce(self) -> None:
        self.manifest.wake.debounce_file.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.wake.debounce_file.write_text(str(time.time()), encoding="utf-8")

    def _prepare(self) -> Path:
        self.memory.ensure_layout()
        self.checkpoints.ensure()
        snapshot = self.memory.write_bootstrap_snapshot(self.manifest.wake.bootstrap_snapshot)
        self.manifest.wake.wakes_dir.mkdir(parents=True, exist_ok=True)
        return snapshot

    def run(self, *, dry_run: bool = False, mini_count: int | None = None) -> WakeRunResult:
        total = mini_count if mini_count is not None else self.manifest.wake.mini_invocations
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = self.manifest.wake.wakes_dir / f"wake-{ts}.log"

        if self._debounced():
            return WakeRunResult(
                log_path=log_path,
                mini_runs=0,
                critique_ran=False,
                dry_run=dry_run,
                debounced=True,
                locked=False,
            )

        snapshot = self._prepare()
        lines: list[str] = [
            f"=== openfdd wake start {ts} ===",
            f"repo_root={self.manifest.repo_root}",
            f"workspace={self.manifest.workspace_dir}",
            f"bootstrap_snapshot={snapshot}",
        ]

        critique_ran = False
        failure: str | None = None
        mini_completed = 0
        try:
            with wake_lock(self.manifest.wake.lock_file):
                for index in range(1, total + 1):
                    if self.manifest.wake.stop_early_file.is_file():
                        lines.append(f"early stop before mini {index}")
                        self.manifest.wake.stop_early_file.unlink(missing_ok=True)
                        break
                    message = build_mini_wake_message(
                        self.manifest,
                        invocation=index,
                        total=total,
                    )
                    inv = build_invocation(
                        self.manifest,
                        message,
                        model=self.manifest.wake.mini_model,
                    )
                    lines.append(f"--- mini {index}/{total} ---")
                    if dry_run or not codex_available(self.manifest.codex_bin):
                        lines.append(dry_run_command(inv))
                    else:
                        code = run_invocation(inv, transcript=log_path)
                        lines.append(f"mini {index} exit={code}")
                        if code != 0:
                            failure = f"mini {index} failed exit={code}"
                            break
                    mini_completed = index

                if failure is not None:
                    lines.append(failure)
                else:
                    critique_message = build_critique_wake_message(self.manifest, mini_count=total)
                    critique_inv = build_invocation(
                        self.manifest,
                        critique_message,
                        model=self.manifest.wake.critique_model,
                    )
                    lines.append("--- critique ---")
                    critique_ran = True
                    if dry_run or not codex_available(self.manifest.codex_bin):
                        lines.append(dry_run_command(critique_inv))
                    else:
                        code = run_invocation(critique_inv, transcript=log_path)
                        lines.append(f"critique exit={code}")
                        if code != 0:
                            failure = f"critique failed exit={code}"
        except WakeLockError as exc:
            lines.append(str(exc))
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return WakeRunResult(
                log_path=log_path,
                mini_runs=0,
                critique_ran=False,
                dry_run=dry_run,
                debounced=False,
                locked=True,
            )

        if failure is not None:
            lines.append(f"=== openfdd wake failed {ts} ===")
        else:
            lines.append(f"=== openfdd wake end {ts} ===")
        header = "\n".join(lines) + "\n"
        if log_path.is_file():
            existing = log_path.read_text(encoding="utf-8")
            log_path.write_text(header + existing, encoding="utf-8")
        else:
            log_path.write_text(header, encoding="utf-8")

        if failure is not None:
            self.memory.append_daily(f"wake failed log={log_path.name}: {failure}")
            return WakeRunResult(
                log_path=log_path,
                mini_runs=mini_completed,
                critique_ran=critique_ran,
                dry_run=dry_run,
                debounced=False,
                locked=False,
            )

        self._stamp_debounce()
        self.memory.append_daily(f"wake complete log={log_path.name} minis={total}")
        return WakeRunResult(
            log_path=log_path,
            mini_runs=total,
            critique_ran=critique_ran,
            dry_run=dry_run,
            debounced=False,
            locked=False,
        )
