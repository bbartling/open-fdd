"""Rules API: list and read FDD rule YAML files from the configured rules_dir (GET /config)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from open_fdd.platform.config import get_platform_settings

router = APIRouter(prefix="/rules", tags=["rules"])


def _rules_dir_resolved() -> Path:
    """Return resolved rules_dir from platform config (RDF-backed)."""
    settings = get_platform_settings()
    raw = getattr(settings, "rules_dir", None) or "analyst/rules"
    return Path(raw).resolve()


@router.get("", summary="List rule YAML files")
def list_rules():
    """Return the configured rules_dir path and the list of .yaml filenames in it. Path comes from GET /config (RDF)."""
    base = _rules_dir_resolved()
    if not base.is_dir():
        return {"rules_dir": str(base), "files": [], "error": "rules_dir is not a directory"}
    files = sorted(f.name for f in base.glob("*.yaml"))
    return {"rules_dir": str(base), "files": files}


@router.get("/{filename}", response_class=PlainTextResponse, summary="Get rule file content")
def get_rule_file(filename: str):
    """Return the raw content of a single .yaml file in the configured rules_dir. Filename must be a bare name (e.g. sensor_bounds.yaml)."""
    if not filename.endswith(".yaml"):
        raise HTTPException(400, "Only .yaml files are allowed")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    base = _rules_dir_resolved()
    if not base.is_dir():
        raise HTTPException(404, "rules_dir not found")
    path = (base / filename).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid filename") from None
    if not path.is_file() or not path.name.endswith(".yaml"):
        raise HTTPException(404, "Rule file not found")
    try:
        return PlainTextResponse(content=path.read_text(encoding="utf-8"))
    except OSError as e:
        raise HTTPException(500, f"Cannot read file: {e}") from e
