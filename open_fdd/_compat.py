"""Compatibility re-exports (Python 3.11+ ships enum.StrEnum; kept so existing imports keep working)."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["StrEnum"]
