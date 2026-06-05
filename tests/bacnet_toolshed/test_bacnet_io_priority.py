"""Operator (interactive) BACnet requests must preempt background poll scrape."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from bacnet_toolshed.bacnet_io_priority import (  # noqa: E402
    BacnetIoInterrupted,
    BacnetPriority,
    init_loop_state,
    reset_loop_state_for_tests,
    run_bacnet_op,
)


def _run(coro):
    return asyncio.run(coro)


def test_interactive_preempts_background_scrape():
    reset_loop_state_for_tests()
    init_loop_state(asyncio.Lock())
    events: list[str] = []

    async def background(app) -> str:
        events.append("bg:start")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            events.append("bg:cancelled")
            raise
        events.append("bg:done")
        return "bg"

    async def interactive(app) -> str:
        events.append("ui:start")
        await asyncio.sleep(0.01)
        events.append("ui:done")
        return "ui"

    async def _exercise() -> None:
        bg_task = asyncio.create_task(
            run_bacnet_op(lambda app: background(app), lambda: "app", priority=BacnetPriority.BACKGROUND)
        )
        await asyncio.sleep(0.05)
        result = await run_bacnet_op(
            lambda app: interactive(app), lambda: "app", priority=BacnetPriority.INTERACTIVE
        )
        with pytest.raises(BacnetIoInterrupted):
            await bg_task
        assert result == "ui"
        assert events[0] == "bg:start"
        assert "bg:cancelled" in events
        assert events.index("ui:start") < events.index("ui:done")
        assert events.index("ui:done") == len(events) - 1

    _run(_exercise())
    reset_loop_state_for_tests()


def test_background_waits_for_interactive_to_finish():
    reset_loop_state_for_tests()
    init_loop_state(asyncio.Lock())
    order: list[str] = []

    async def interactive(app) -> None:
        order.append("ui:start")
        await asyncio.sleep(0.05)
        order.append("ui:done")

    async def background(app) -> None:
        order.append("bg:start")
        order.append("bg:done")

    async def _exercise() -> None:
        ui_task = asyncio.create_task(
            run_bacnet_op(lambda app: interactive(app), lambda: "app", priority=BacnetPriority.INTERACTIVE)
        )
        await asyncio.sleep(0.01)
        bg_task = asyncio.create_task(
            run_bacnet_op(lambda app: background(app), lambda: "app", priority=BacnetPriority.BACKGROUND)
        )
        await asyncio.gather(ui_task, bg_task)
        assert order == ["ui:start", "ui:done", "bg:start", "bg:done"]

    _run(_exercise())
    reset_loop_state_for_tests()
