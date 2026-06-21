from __future__ import annotations

import pytest
from bacpypes3.apdu import ErrorRejectAbortNack

from bacnet_toolshed import bacnet_override_scan_loop as loop
from bacnet_toolshed.rpm import read_multiple_chunked


class FakeBacnetError(ErrorRejectAbortNack):
    """Test double for BACpypes Error/Reject/Abort/Nack responses.

    BACpypes3 raises these from APDU paths as BaseException subclasses, not
    normal Exception subclasses. The override scan must treat them as BACnet
    device errors and keep the background thread alive.
    """


@pytest.mark.asyncio
async def test_rpm_catches_bacpypes_error_reject_abort_nack():
    class FakeApp:
        async def read_property_multiple(self, address_obj, parameter_list):
            raise FakeBacnetError(
                "read-property-multiple: property: unknown-property"
            )

    result = await read_multiple_chunked(
        FakeApp(),
        "192.168.1.25",
        {"analog-input,1": ["object-name", "present-value"]},
        chunk_size=1,
    )

    assert result["analog-input,1:object-name"] is None
    assert result["analog-input,1:present-value"] is None


def test_override_scan_cycle_survives_bacpypes_error(monkeypatch):
    calls: dict[str, object] = {
        "advanced": False,
        "recorded": False,
    }

    monkeypatch.setattr(
        loop,
        "list_devices_for_scan",
        lambda: [{"device_instance": 12345, "device_address": "192.168.1.25"}],
    )
    monkeypatch.setattr(loop, "scan_status", lambda: {"cursor": 0})
    monkeypatch.setattr(loop, "advance_cursor", lambda count: calls.update(advanced=True))
    monkeypatch.setattr(
        loop,
        "record_scan_error",
        lambda **kwargs: calls.update(recorded=True, error_kwargs=kwargs),
    )

    def run_bacnet_sync(_runner):
        raise FakeBacnetError(
            "read-property-multiple: property: unknown-property"
        )

    result = loop.run_override_scan_cycle(run_bacnet_sync)

    assert result["ok"] is False
    assert result["scanned_device"] == 12345
    assert "unknown-property" in result["error"]
    assert calls["advanced"] is True
    assert calls["recorded"] is True

    error_kwargs = calls["error_kwargs"]
    assert error_kwargs["device_instance"] == 12345
    assert error_kwargs["device_address"] == "192.168.1.25"
    assert "unknown-property" in error_kwargs["error"]
