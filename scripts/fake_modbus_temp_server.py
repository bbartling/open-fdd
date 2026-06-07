#!/usr/bin/env python3
"""Minimal Modbus TCP server — fake zone temperature sensor (holding register).

Serves temperature as uint16 at a configurable holding register address.
Raw register value = round(temp_f * scale_factor); default scale_factor=10
so 72.5 °F is stored as 725 and decoded with scale=0.1 in the Open-FDD driver.

Examples:
  ./scripts/fake_modbus_temp_server.py
  ./scripts/fake_modbus_temp_server.py --port 5502 --temp 68.0 --drift 0.05
  ./scripts/fake_modbus_temp_server.py --port 5502 --flatline 72.5

Bind defaults to 127.0.0.1:5502 (non-privileged; use 502 only with permission).
"""

from __future__ import annotations

import argparse
import math
import signal
import socket
import struct
import sys
import threading
import time
from typing import Callable


def _temp_to_register(temp_f: float, scale: float) -> int:
    return max(0, min(65535, int(round(float(temp_f) * scale))))


class FakeTempSensor:
    """Thread-safe holding-register bank for one temperature sensor."""

    def __init__(
        self,
        *,
        address: int = 100,
        temp_f: float = 72.5,
        scale: float = 10.0,
        drift_per_s: float = 0.0,
        flatline: float | None = None,
    ) -> None:
        self.address = int(address)
        self.scale = float(scale)
        self._lock = threading.Lock()
        self._flatline = flatline
        self._temp = float(flatline if flatline is not None else temp_f)
        self._drift_per_s = float(drift_per_s)
        self._started = time.monotonic()
        self.holding: dict[int, int] = {self.address: _temp_to_register(self._temp, self.scale)}

    def current_temp(self) -> float:
        with self._lock:
            if self._flatline is not None:
                self._temp = float(self._flatline)
            elif self._drift_per_s:
                elapsed = time.monotonic() - self._started
                self._temp = self._temp + self._drift_per_s * elapsed
            reg = _temp_to_register(self._temp, self.scale)
            self.holding[self.address] = reg
            return self._temp

    def read_holding(self, start: int, count: int) -> list[int] | None:
        self.current_temp()
        with self._lock:
            end = start + count
            if start < 0 or count < 1 or end > 65536:
                return None
            out: list[int] = []
            for addr in range(start, end):
                if addr not in self.holding:
                    return None
                out.append(int(self.holding[addr]) & 0xFFFF)
            return out


def _parse_request(data: bytes) -> tuple[int, int, int, int, int] | tuple[None, bytes]:
    """Return (transaction_id, unit_id, function, start, count) or (None, error_response)."""
    if len(data) < 12:
        return (None, b"")
    transaction_id, protocol_id, length = struct.unpack(">HHH", data[:6])
    if protocol_id != 0:
        return (None, b"")
    unit_id = data[6]
    pdu = data[7 : 6 + length]
    if len(pdu) < 5:
        return (None, b"")
    function = pdu[0]
    if function == 0x03:
        start, count = struct.unpack(">HH", pdu[1:5])
        return (transaction_id, unit_id, function, start, count)
    if function == 0x04:
        start, count = struct.unpack(">HH", pdu[1:5])
        return (transaction_id, unit_id, function, start, count)
    exc_pdu = struct.pack(">BB", function | 0x80, 0x01)
    return (None, _build_response(transaction_id, unit_id, exc_pdu))


def _build_response(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    length = len(pdu) + 1
    return struct.pack(">HHH", transaction_id, 0, length) + bytes([unit_id]) + pdu


def _handle_fc34(
    sensor: FakeTempSensor,
    transaction_id: int,
    unit_id: int,
    function: int,
    start: int,
    count: int,
) -> bytes:
    words = sensor.read_holding(start, count)
    if words is None:
        exc_pdu = struct.pack(">BB", function | 0x80, 0x02)
        return _build_response(transaction_id, unit_id, exc_pdu)
    body = struct.pack(">BB", function, len(words) * 2)
    for word in words:
        body += struct.pack(">H", word)
    return _build_response(transaction_id, unit_id, body)


def _client_loop(conn: socket.socket, sensor: FakeTempSensor) -> None:
    try:
        while True:
            data = conn.recv(256)
            if not data:
                break
            parsed = _parse_request(data)
            if parsed[0] is None:
                if parsed[1]:
                    conn.sendall(parsed[1])
                continue
            transaction_id, unit_id, function, start, count = parsed
            if function in (0x03, 0x04):
                resp = _handle_fc34(sensor, transaction_id, unit_id, function, start, count)
                conn.sendall(resp)
            else:
                exc_pdu = struct.pack(">BB", function | 0x80, 0x01)
                conn.sendall(_build_response(transaction_id, unit_id, exc_pdu))
    except OSError:
        pass
    finally:
        conn.close()


def serve(
    host: str,
    port: int,
    sensor: FakeTempSensor,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(8)
    sock.settimeout(1.0)
    print(f"fake Modbus TCP temp sensor listening on {host}:{port}", flush=True)
    print(
        f"  unit 1, holding reg {sensor.address}, temp={sensor._temp:.1f} °F "
        f"(raw={sensor.holding[sensor.address]}, scale={sensor.scale})",
        flush=True,
    )
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            threading.Thread(
                target=_client_loop,
                args=(conn, sensor),
                daemon=True,
            ).start()
    finally:
        sock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5502)
    parser.add_argument("--unit-id", type=int, default=1)
    parser.add_argument("--address", type=int, default=100, help="Holding register address")
    parser.add_argument("--temp", type=float, default=72.5, help="Starting temperature (°F)")
    parser.add_argument("--scale", type=float, default=10.0, help="Register = temp * scale")
    parser.add_argument("--drift", type=float, default=0.02, help="°F/s drift (0 = static)")
    parser.add_argument("--flatline", type=float, default=None, help="Fixed temperature (disables drift)")
    args = parser.parse_args(argv)

    if args.unit_id != 1:
        print("warning: server accepts any unit id in requests; --unit-id is informational", file=sys.stderr)

    sensor = FakeTempSensor(
        address=args.address,
        temp_f=args.temp,
        scale=args.scale,
        drift_per_s=0.0 if args.flatline is not None else args.drift,
        flatline=args.flatline,
    )

    stop = threading.Event()

    def _stop(*_a: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    serve(args.host, args.port, sensor, stop_event=stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
