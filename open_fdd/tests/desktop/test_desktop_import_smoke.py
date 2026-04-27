from __future__ import annotations

import open_fdd


def test_desktop_entrypoint_exposed() -> None:
    assert hasattr(open_fdd, "GUI")

