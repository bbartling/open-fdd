from __future__ import annotations

from .codex_launcher import build_invocation, codex_available, dry_run_command, run_invocation
from .cron.scheduler import CronScheduler
from .cron.store import CronStore
from .manifest import Manifest
from .memory.store import MemoryStore
from .prompts import build_critique_wake_message, build_mini_wake_message, build_system_prompt, skill_paths
from .wake.runner import WakeRunner


def print_status(manifest: Manifest) -> None:
    memory = MemoryStore(manifest)
    memory.ensure_layout()
    print("Open-FDD agent shell")
    print(f"  manifest: {manifest.manifest_path}")
    print(f"  project:  {manifest.project_name}")
    print(f"  workspace:{manifest.workspace_dir}")
    print(f"  memory:   {manifest.memory.bootstrap_file}")
    print(f"  cron:     {manifest.cron.jobs_file}")
    print(f"  engine:   {manifest.engine_package} ({manifest.engine_install})")
    print(f"  skills:   {', '.join(manifest.agent_skills) or '(none)'}")
    print(f"  codex:    {manifest.codex_bin} ({'found' if codex_available(manifest.codex_bin) else 'missing'})")


def _handle_memory_command(manifest: Manifest, line: str) -> bool:
    store = MemoryStore(manifest)
    store.ensure_layout()
    parts = line.split(maxsplit=2)
    if line == "/memory":
        print(store.read_bootstrap()[:2000])
        return True
    if len(parts) >= 2 and parts[1] == "search":
        query = line.split("search", 1)[1].strip()
        for path, lineno, text in store.search(query):
            print(f"{path}:{lineno}: {text}")
        return True
    if len(parts) >= 2 and parts[1] == "remember":
        text = line.split("remember", 1)[1].strip()
        path = store.remember(text)
        print(f"remembered in {path}")
        return True
    if len(parts) >= 2 and parts[1] == "divergence":
        print(f"open divergence entries: {store.count_open_divergence_entries()}")
        print(store.read_divergence_log()[:2000])
        return True
    if len(parts) >= 2 and parts[1] == "bootstrap":
        path = store.write_bootstrap_snapshot(manifest.wake.bootstrap_snapshot)
        print(f"wrote {path}")
        return True
    return False


def _handle_cron_command(manifest: Manifest, line: str, *, dry_run: bool) -> bool:
    store = CronStore.from_manifest(manifest)
    scheduler = CronScheduler(manifest)
    parts = line.split()
    if line == "/cron" or line == "/cron list":
        for job in store.load_jobs():
            state = store.job_state(job.id)
            print(
                f"{job.id}\t{job.name}\t{job.service}\t"
                f"next={state.get('next_run_at')}"
            )
        return True
    if len(parts) >= 2 and parts[1] == "tick":
        for result in scheduler.tick(dry_run=dry_run):
            print(f"{result.job_id}\t{result.status}\t{result.message}")
        return True
    if len(parts) >= 3 and parts[1] == "run":
        job = store.get_job(parts[2])
        if job is None:
            print(f"unknown job: {parts[2]}")
            return True
        result = scheduler.run_job(job, dry_run=dry_run)
        print(f"{result.status}: {result.message}")
        return True
    return False


def run_repl(manifest: Manifest, *, dry_run: bool = False) -> int:
    manifest.ensure_workspace_dirs()
    MemoryStore(manifest).ensure_layout()
    CronStore.from_manifest(manifest).ensure_layout()
    print_status(manifest)
    print(
        "Commands: /skills /plan /verify /engine-check /open-workspace "
        "/memory [/memory search|remember|divergence|bootstrap] "
        "/wake [dry|mini|critique] /cron [list|tick|run <id>] /quit"
    )
    while True:
        try:
            line = input("openfdd> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in {"/quit", "/exit"}:
            return 0
        if line == "/skills":
            for path in skill_paths(manifest.repo_root, manifest.agent_skills):
                print(f"  - {path.parent.name}: {path}")
            continue
        if line == "/plan":
            print(build_system_prompt(manifest)[:4000])
            continue
        if line == "/verify":
            inv = build_invocation(manifest, "Summarize verification steps for the selected skills.")
            print(dry_run_command(inv))
            continue
        if line == "/engine-check":
            try:
                import open_fdd.engine  # noqa: F401

                print("open_fdd.engine import OK")
            except ImportError as exc:
                print(f"engine import failed: {exc}")
            continue
        if line == "/open-workspace":
            print(manifest.workspace_dir)
            continue
        if line.startswith("/memory"):
            if _handle_memory_command(manifest, line):
                continue
        if line.startswith("/cron"):
            if _handle_cron_command(manifest, line, dry_run=dry_run):
                continue
        if line == "/wake" or line == "/wake dry":
            result = WakeRunner(manifest).run(dry_run=dry_run or line.endswith("dry"))
            print(f"wake log: {result.log_path} debounced={result.debounced} locked={result.locked}")
            continue
        if line == "/wake mini":
            inv = build_invocation(
                manifest,
                build_mini_wake_message(manifest, invocation=1, total=manifest.wake.mini_invocations),
            )
            print(dry_run_command(inv))
            continue
        if line == "/wake critique":
            inv = build_invocation(
                manifest,
                build_critique_wake_message(manifest, mini_count=manifest.wake.mini_invocations),
            )
            print(dry_run_command(inv))
            continue
        inv = build_invocation(manifest, line)
        if dry_run:
            print(dry_run_command(inv))
            continue
        if not codex_available(manifest.codex_bin):
            print(f"Codex binary '{manifest.codex_bin}' not found on PATH.")
            print(dry_run_command(inv))
            continue
        return run_invocation(inv)
