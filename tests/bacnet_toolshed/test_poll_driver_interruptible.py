"""Interruptible poll scrape yields between devices for operator preemption."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from bacnet_toolshed.poll_driver import poll_once  # noqa: E402


class _Point:
    def __init__(self, point_id: str, dev_inst: int, dev_addr: str, obj_type: str, obj_inst: int):
        self.point_id = point_id
        self.device_instance = dev_inst
        self.site_id = "demo"
        self.building_id = "b1"
        self.system_id = "s1"
        self.series_id = point_id
        self.object_type = obj_type
        self.object_instance = obj_inst
        self.units = "degF"

    def rpm_key(self) -> str:
        return f"{self.object_type},{self.object_instance}"


def test_interruptible_poll_checks_cancel_between_devices(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[str] = []
    hold_second = asyncio.Event()
    second_started = asyncio.Event()

    async def fake_rpm(app, dev_addr, rpm_objects):
        calls.append(dev_addr)
        if dev_addr == "2000:8":
            second_started.set()
            await hold_second.wait()
        return {k: 1.0 for k in rpm_objects}

    monkeypatch.setattr("bacnet_toolshed.poll_driver.read_multiple_chunked", fake_rpm)

    points_by_device = {
        (5007, "2000:7"): [_Point("p1", 5007, "2000:7", "analog-input", 1)],
        (5008, "2000:8"): [_Point("p2", 5008, "2000:8", "analog-input", 2)],
    }
    out = tmp_path / "samples.csv"

    async def _exercise() -> None:
        task = asyncio.create_task(
            poll_once(object(), points_by_device, output_csv=out, dry_run=False, interruptible=True)
        )
        await second_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_exercise())
    assert calls == ["2000:7", "2000:8"]
