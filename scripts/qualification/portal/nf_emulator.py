#!/usr/bin/env python3
"""Loopback-only Normal Framework portal emulator for disposable qualification.

Replays the recorded fixture in ``scripts/qualification/fixtures/nf_emulator``
through the three read endpoints Central uses:

* ``POST /api/v1/auth/token``  - fixed non-secret lab token
* ``POST /api/v1/point/query`` - latest value per fixture point
* ``GET  /api/v1/point/data``  - history replayed on a 5 minute grid

``POST /api/v1/point/data`` is an upstream write. It is refused with 405 and
logged as ``forbidden_write`` so the recipe can fail the run. Every request is
logged as one JSON line without query strings, headers, or bodies.

Stdlib only. It refuses to bind anything but a loopback address and never
opens an outbound connection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nf_emulator" / "points.json"
GRID_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024
MAX_WINDOW_SECONDS = 7 * 24 * 3600
FORBIDDEN_WRITE = ("POST", "/api/v1/point/data")


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "openfdd_nf_emulator_fixture_v1":
        raise ValueError("unexpected NF emulator fixture schema")
    points = data.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("fixture needs at least one point")
    for point in points:
        recorded = point.get("recorded")
        if not isinstance(point.get("uuid"), str) or not isinstance(recorded, list) or not recorded:
            raise ValueError("each fixture point needs uuid and recorded values")
    return data


def _iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _grid_floor(epoch: int) -> int:
    return epoch - (epoch % GRID_SECONDS)


def recorded_value(point: dict[str, Any], epoch: int) -> float:
    values = point["recorded"]
    return float(values[(epoch // GRID_SECONDS) % len(values)])


def point_query_body(fixture: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    epoch = _grid_floor(int(now.timestamp()))
    stamp = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
    return {
        "points": [
            {
                "name": p.get("name"),
                "uuid": p["uuid"],
                "units": p.get("units"),
                "attrs": p.get("attrs") or {},
                "latestValue": {
                    "double": recorded_value(p, epoch),
                    "ts": _iso(stamp),
                    "quality": "good",
                },
            }
            for p in fixture["points"]
        ]
    }


def history_body(
    fixture: dict[str, Any], uuids: list[str], start: int, end: int, now: dt.datetime
) -> dict[str, Any]:
    end = min(end, int(now.timestamp()))
    if end < start or end - start > MAX_WINDOW_SECONDS:
        raise ValueError("history window out of bounds")
    wanted = set(uuids)
    data = []
    for p in fixture["points"]:
        if p["uuid"] not in wanted:
            continue
        values = []
        epoch = _grid_floor(start)
        if epoch < start:
            epoch += GRID_SECONDS
        while epoch <= end:
            values.append(
                {
                    "ts": _iso(dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)),
                    "double": recorded_value(p, epoch),
                    "quality": "good",
                }
            )
            epoch += GRID_SECONDS
        data.append({"uuid": p["uuid"], "units": p.get("units"), "values": values})
    return {"data": data}


def make_handler(fixture: dict[str, Any], clock=lambda: dt.datetime.now(dt.timezone.utc)):
    class Handler(BaseHTTPRequestHandler):
        server_version = "openfdd-nf-emulator/1"
        sys_version = ""

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _log(self, status: int, event: str = "nf_emulator_request") -> None:
            path = urlsplit(self.path).path
            line = {"event": event, "method": self.command, "path": path, "status": status}
            sys.stdout.write(json.dumps(line, sort_keys=True) + "\n")
            sys.stdout.flush()

        def _send(self, status: int, payload: dict[str, Any], event: str = "nf_emulator_request") -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            self._log(status, event)

        def _drain_body(self) -> bool:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return False
            if length < 0 or length > MAX_BODY_BYTES:
                return False
            if length:
                self.rfile.read(length)
            return True

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if (self.command, path) == FORBIDDEN_WRITE:
                self._drain_body()
                self._send(405, {"error": "point writes are not emulated"}, event="forbidden_write")
                return
            if not self._drain_body():
                self._send(413, {"error": "body too large"})
                return
            if path == "/api/v1/auth/token":
                self._send(200, dict(fixture.get("token") or {}))
            elif path == "/api/v1/point/query":
                self._send(200, point_query_body(fixture, clock()))
            else:
                self._send(404, {"error": "not emulated"})

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            if parts.path == "/healthz":
                self._send(200, {"ok": True})
                return
            if parts.path != "/api/v1/point/data":
                self._send(404, {"error": "not emulated"})
                return
            query = parse_qs(parts.query)
            try:
                start = int(query["from.seconds"][0])
                end = int(query["to.seconds"][0])
                body = history_body(fixture, query.get("uuids", []), start, end, clock())
            except (KeyError, ValueError, IndexError):
                self._send(400, {"error": "bad history request"})
                return
            self._send(200, body)

        def _refuse(self) -> None:
            self._send(405, {"error": "method not emulated"})

        do_PUT = do_DELETE = do_PATCH = _refuse  # noqa: N815

    return Handler


def require_loopback(host: str) -> None:
    if host == "localhost":
        return
    if not ipaddress.ip_address(host).is_loopback:
        raise SystemExit(f"refusing non-loopback bind {host!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18089)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    require_loopback(args.bind)
    fixture = load_fixture(args.fixture)
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(fixture))
    sys.stdout.write(json.dumps({"event": "nf_emulator_listening", "port": args.port}) + "\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
