from __future__ import annotations

import os
from pathlib import Path


def fallback_api_key_from_env_files() -> str:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parents[1] / "stack" / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if not line.startswith("OFDD_ONBOARD_API_KEY="):
                continue
            value = line.split("=", 1)[1].strip().strip("'").strip('"')
            if value:
                return value
    return os.getenv("OFDD_ONBOARD_API_KEY", "").strip()
