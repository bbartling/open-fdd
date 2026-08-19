#!/usr/bin/env python3
"""Vibe19 (pandas) WattLab oracle dump for Building 100 parity.

Prefers a running GHCR vibe19 container (`docker exec`). Falls back to a
local playground checkout. Not tools/wattlab_export. Default runs cookbook
rules (no --skip-rules).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIBE19 = Path("/home/ben/py-bacnet-stacks-playground/vibe_code_apps_19")
DEFAULT_PKG = Path("/home/ben/raw_BUILDING_100_openfdd.zip")
DEFAULT_SCHED = ROOT / "reports/wattlab-parity/fixtures/schedule_b100_7to5.json"
DEFAULT_OUT = ROOT / "reports/wattlab-parity/artifacts/vibe19_oracle"
DEFAULT_CONTAINER = "vibe19"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
        return h.hexdigest()


def _docker_running(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _docker_inspect(name: str) -> dict:
    r = subprocess.run(
        [
            "docker",
            "inspect",
            name,
            "--format",
            '{{json .}}',
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def _load_afdd(vibe19_root: Path):
    script = vibe19_root / "scripts" / "agent_afdd.py"
    if not script.is_file():
        raise SystemExit(f"vibe19 agent_afdd.py not found: {script}")
    sys.path.insert(0, str(vibe19_root))
    spec = importlib.util.spec_from_file_location("vibe19_agent_afdd", script)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def _maybe_reexec_vibe19_venv(vibe19_root: Path) -> None:
    venv_py = vibe19_root / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    if Path(sys.executable).resolve() == venv_py.resolve():
        return
    os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])


def _stamp_open_fdd_host() -> tuple[str | None, str | None, str | None]:
    of_ver = of_sha = cat_hash = None
    try:
        import open_fdd

        of_ver = getattr(open_fdd, "__version__", None)
        man = {}
        if hasattr(open_fdd, "manifest"):
            man = open_fdd.manifest() or {}
        of_ver = man.get("open_fdd_python_version") or of_ver
        of_sha = man.get("open_fdd_python_git_sha")
        from open_fdd.catalog import rule_catalog_hash

        cat_hash = rule_catalog_hash()
    except Exception as exc:  # pragma: no cover
        print(f"warning: could not read host open_fdd manifest: {exc}", file=sys.stderr)
    return of_ver, of_sha, cat_hash


def _stamp_open_fdd_docker(container: str) -> tuple[str | None, str | None, str | None]:
    code = (
        "import json,open_fdd\n"
        "man=open_fdd.manifest() if hasattr(open_fdd,'manifest') else {}\n"
        "h=None\n"
        "try:\n"
        " from open_fdd.catalog import rule_catalog_hash as f\n"
        " h=f()\n"
        "except Exception:\n"
        " pass\n"
        "print(json.dumps({'v': man.get('open_fdd_python_version') or getattr(open_fdd,'__version__',None),'sha': man.get('open_fdd_python_git_sha'),'h': h}))\n"
    )
    r = subprocess.run(
        ["docker", "exec", container, "python", "-c", code],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"warning: docker open_fdd stamp failed: {r.stderr}", file=sys.stderr)
        return None, None, None
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
        return d.get("v"), d.get("sha"), d.get("h")
    except (json.JSONDecodeError, IndexError):
        return None, None, None


def _afdd_argv(package: str, out: str, schedule: str, profile: str, skip_rules: bool) -> list[str]:
    argv = [
        "--package",
        package,
        "--out",
        out,
        "--export-profile",
        profile,
        "--schedule",
        schedule,
        "--no-bootstrap",
    ]
    if skip_rules:
        argv += ["--run-analytics", "--run-rcx"]
    else:
        argv += ["--run-all"]
    return argv


def _run_docker(
    container: str,
    package: Path,
    schedule: Path,
    out: Path,
    profile: str,
    skip_rules: bool,
) -> int:
    host_parity = ROOT / "reports/wattlab-parity"
    host_parity.mkdir(parents=True, exist_ok=True)
    # Bind is expected at /data/parity on the container (started by the soak).
    c_pkg = "/data/raw_BUILDING_100_openfdd.zip"
    c_sched = "/data/parity/fixtures/schedule_b100_7to5.json"
    c_out = "/data/parity/artifacts/vibe19_oracle"
    if package.resolve() != DEFAULT_PKG.resolve():
        print(
            f"warning: docker dump uses bind {c_pkg}; --package {package} ignored",
            file=sys.stderr,
        )
    argv = _afdd_argv(c_pkg, c_out, c_sched, profile, skip_rules)
    cmd = ["docker", "exec", container, "python", "scripts/agent_afdd.py", *argv]
    print("docker:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd)
    # Copy out if agent wrote to c_out which is bind-mounted to host_parity/artifacts
    bind_out = host_parity / "artifacts" / "vibe19_oracle"
    if bind_out.resolve() != out.resolve() and bind_out.is_dir():
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(bind_out, out)
    return proc.returncode


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, default=DEFAULT_PKG)
    p.add_argument("--schedule", type=Path, default=DEFAULT_SCHED)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--vibe19-root",
        type=Path,
        default=DEFAULT_VIBE19,
        help="Playground vibe_code_apps_19 root (host fallback)",
    )
    p.add_argument("--container", default=DEFAULT_CONTAINER)
    p.add_argument("--no-docker", action="store_true")
    p.add_argument(
        "--profile",
        choices=("summary", "diagnostic", "forensic"),
        default="diagnostic",
    )
    p.add_argument(
        "--skip-rules",
        action="store_true",
        help="Skip cookbook FDD rules (not the default soak path)",
    )
    args = p.parse_args()

    if args.skip_rules:
        print("warning: --skip-rules is not the B100 soak path", file=sys.stderr)

    if not args.package.is_file():
        print(f"package not found: {args.package}", file=sys.stderr)
        return 2
    if not args.schedule.is_file():
        print(f"schedule not found: {args.schedule}", file=sys.stderr)
        return 2

    use_docker = (not args.no_docker) and _docker_running(args.container)
    docker_meta = {}
    of_ver = of_sha = cat_hash = None
    rc: int

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    if use_docker:
        insp = _docker_inspect(args.container)
        labels = (insp.get("Config") or {}).get("Labels") or {}
        docker_meta = {
            "container": args.container,
            "image": (insp.get("Config") or {}).get("Image"),
            "image_id": insp.get("Image"),
            "revision": labels.get("org.opencontainers.image.revision"),
        }
        rc = _run_docker(
            args.container,
            args.package,
            args.schedule,
            args.out,
            args.profile,
            args.skip_rules,
        )
        of_ver, of_sha, cat_hash = _stamp_open_fdd_docker(args.container)
    else:
        vibe19 = args.vibe19_root.resolve()
        _maybe_reexec_vibe19_venv(vibe19)
        afdd_main = _load_afdd(vibe19)
        argv = _afdd_argv(
            str(args.package),
            str(args.out),
            str(args.schedule),
            args.profile,
            args.skip_rules,
        )
        rc = afdd_main(argv)
        of_ver, of_sha, cat_hash = _stamp_open_fdd_host()

    vh = args.out / "vav_health_matrix.csv"
    meta = {
        "side": "vibe19_oracle",
        "mode": "docker" if use_docker else "host_playground",
        "docker": docker_meta,
        "package": str(args.package),
        "package_sha256": _sha256(args.package),
        "schedule": str(args.schedule),
        "profile": args.profile,
        "out": str(args.out),
        "skip_rules": bool(args.skip_rules),
        "open_fdd_python_version": of_ver,
        "open_fdd_python_git_sha": of_sha,
        "rule_catalog_hash": cat_hash,
        "vav_health_matrix_present": vh.is_file() and vh.stat().st_size > 0,
        "python": sys.executable,
        "agent_afdd_rc": rc,
    }
    (args.out / "parity_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    zip_path = args.out.parent / "vibe19_oracle_summary.zip"
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", args.out)
    print(f"oracle dump -> {args.out}")
    print(f"oracle zip  -> {zip_path}")
    print(f"open_fdd    -> {of_ver} catalog={cat_hash} docker={use_docker}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
