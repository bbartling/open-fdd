"""Static file helpers for the operator dashboard SPA."""

from __future__ import annotations

from starlette.staticfiles import StaticFiles

# Vite emits content-hashed filenames under /assets — safe to cache for one year.
ASSETS_CACHE_CONTROL = "public, max-age=31536000, immutable"


class CachedStaticFiles(StaticFiles):
    """StaticFiles with long-lived cache headers for immutable hashed assets."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = ASSETS_CACHE_CONTROL
        return response
