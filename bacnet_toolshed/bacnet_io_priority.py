"""Priority scheduling for the single BACnet asyncio stack (operator UI vs background scrape)."""

from __future__ import annotations

import asyncio
from enum import IntEnum
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

AppFactory = Callable[[], Any]
CoroFactory = Callable[[Any], Awaitable[T]]


class BacnetPriority(IntEnum):
    """Lower value = higher priority on the shared BACnet stack."""

    INTERACTIVE = 0  # browser reads/writes, discovery, Who-Is
    BACKGROUND = 10  # scheduled RPM poll scrape


class BacnetIoInterrupted(Exception):
    """Background BACnet work was cancelled for a higher-priority operator request."""


class _LoopState:
    __slots__ = ("serial_lock", "background_task")

    def __init__(self, serial_lock: asyncio.Lock) -> None:
        self.serial_lock = serial_lock
        self.background_task: asyncio.Task[Any] | None = None


_state: _LoopState | None = None


def init_loop_state(serial_lock: asyncio.Lock) -> None:
    global _state
    _state = _LoopState(serial_lock=serial_lock)


def reset_loop_state_for_tests() -> None:
    global _state
    _state = None


async def _interrupt_background() -> None:
    if _state is None:
        return
    bg = _state.background_task
    if bg is None or bg.done():
        return
    bg.cancel()
    try:
        await bg
    except (asyncio.CancelledError, BacnetIoInterrupted):
        pass
    except Exception:
        pass


async def run_bacnet_op(
    coro_factory: CoroFactory[T],
    get_app: AppFactory,
    *,
    priority: BacnetPriority,
) -> T:
    """Run one BACnet coroutine on the dedicated loop with priority-aware preemption."""
    if _state is None:
        raise RuntimeError("BACnet I/O loop state not initialized")

    if priority == BacnetPriority.INTERACTIVE:
        await _interrupt_background()
        async with _state.serial_lock:
            app = get_app()
            return await coro_factory(app)

    async with _state.serial_lock:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("BACnet background op missing task context")
        _state.background_task = task
        try:
            app = get_app()
            return await coro_factory(app)
        except asyncio.CancelledError as exc:
            raise BacnetIoInterrupted("BACnet scrape interrupted for operator request") from exc
        finally:
            _state.background_task = None
