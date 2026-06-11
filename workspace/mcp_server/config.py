from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _repo_root() -> Path:
    env = os.getenv("OPENFDD_REPO_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _portfolio_sites_path(repo: Path, ws: Path) -> Path:
    env = os.getenv("OFDD_PORTFOLIO_SITES_PATH", "").strip()
    if env:
        return Path(env)
    for candidate in (repo / "portfolio" / "sites.json", ws / "portfolio" / "sites.json"):
        if candidate.is_file():
            return candidate
    return repo / "portfolio" / "sites.json"


def _workspace_dir() -> Path:
    env = os.getenv("OPENFDD_WORKSPACE_DIR", "").strip()
    if env:
        return Path(env)
    return _repo_root() / "workspace"


@dataclass(frozen=True)
class McpConfig:
    mode: str
    transport: str
    host: str
    port: int
    bridge_base_url: str
    rag_index_path: Path
    portfolio_sites_path: Path
    default_site_id: str | None
    max_window_minutes: int = 180

    @classmethod
    def from_env(cls) -> McpConfig:
        ws = _workspace_dir()
        repo = _repo_root()
        mode = os.getenv("OFDD_MCP_MODE", "edge").strip().lower() or "edge"
        return cls(
            mode=mode if mode in {"edge", "portfolio"} else "edge",
            transport=os.getenv("OFDD_MCP_TRANSPORT", "streamable-http").strip().lower()
            or "streamable-http",
            host=os.getenv("OFDD_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(os.getenv("OFDD_MCP_PORT", os.getenv("OFDD_MCP_LISTEN_PORT", "8090"))),
            bridge_base_url=os.getenv(
                "OPENFDD_BRIDGE_BASE_URL",
                os.getenv("OFDD_BRIDGE_BASE_URL", "http://127.0.0.1:8765"),
            ).rstrip("/"),
            rag_index_path=Path(
                os.getenv(
                    "OFDD_MCP_RAG_INDEX_PATH",
                    str(ws / "data" / "mcp" / "rag_index.json"),
                )
            ),
            portfolio_sites_path=_portfolio_sites_path(repo, ws),
            default_site_id=(os.getenv("OFDD_MCP_DEFAULT_SITE_ID") or "").strip() or None,
            max_window_minutes=min(180, max(5, int(os.getenv("OFDD_MCP_MAX_WINDOW_MINUTES", "180")))),
        )

    @property
    def memory_path(self) -> Path:
        return _workspace_dir() / "MEMORY.md"

    @property
    def skills_dir(self) -> Path:
        return _repo_root() / "skills"
