"""
Open-FDD desktop application entry points.
"""

from __future__ import annotations

from open_fdd.desktop.ui.launcher import launch_desktop


def GUI() -> int:
    """Launch the PySide6 desktop GUI."""
    return launch_desktop()


def main() -> int:
    """Console script entry point."""
    return GUI()

