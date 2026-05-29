from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    raw = os.environ.get("OPENFDD_REPO_ROOT", "").strip()
    if raw:
        return Path(raw).resolve()
    # workspace/api/openfdd_bridge -> repo root
    return Path(__file__).resolve().parents[3]


def workspace_dir() -> Path:
    raw = os.environ.get("OPENFDD_WORKSPACE_DIR", "").strip()
    if raw:
        return Path(raw).resolve()
    return (repo_root() / "workspace").resolve()


def data_dir() -> Path:
    raw = os.environ.get("OFDD_DESKTOP_DATA_DIR", "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = repo_root() / path
        return path.resolve()
    return (workspace_dir() / "data").resolve()


def bacnet_poll_csv() -> Path:
    return workspace_dir() / "bacnet" / "polls" / "samples.csv"


def static_dashboard_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "app"


def model_json_path() -> Path:
    return data_dir() / "model.json"


def model_ttl_path() -> Path:
    return data_dir() / "data_model.ttl"


def building_alerts_path() -> Path:
    return data_dir() / "building_alerts.json"


def resolve_workdir_under_repo(workdir: str | None) -> Path:
    """Codex/exec cwd must stay inside the repository."""
    repo = repo_root().resolve()
    if not workdir or not str(workdir).strip():
        return repo
    candidate = Path(workdir).resolve()
    try:
        candidate.relative_to(repo)
    except ValueError:
        return repo
    return candidate
