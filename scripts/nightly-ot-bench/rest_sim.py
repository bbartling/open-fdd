#!/usr/bin/env python3
"""Tiny JSON OT control-system simulator for gate 09 (REST/JSON edge driver).

Stdlib only. Endpoints:
  GET  /points/chw_supply_temp  -> {"value": <float>}
  GET  /points/plant_kw         -> {"value": <float>}
  GET  /status                  -> {"ok": true, "mode": "sim"}
  POST /points/chw_setpoint     -> body {"value": N, ...}; stores + echoes
  POST /_kill                   -> process exits (circuit-breaker test)
  GET  /_health                 -> liveness

Auth (optional): Authorization: Bearer <token> OR X-API-Key: <token>
When REST_SIM_TOKEN is set, requests without a matching credential get 401.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("REST_SIM_HOST", "127.0.0.1")
PORT = int(os.environ.get("REST_SIM_PORT", "18765"))
TOKEN = os.environ.get("REST_SIM_TOKEN", "")

STATE = {
    "chw_st": 44.0,
    "plant_kw": 120.5,
    "chw_setpoint": 44.0,
    "posts": 0,
}


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    if not TOKEN:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {TOKEN}":
        return True
    if handler.headers.get("X-API-Key") == TOKEN:
        return True
    if handler.headers.get("X-Api-Key") == TOKEN:
        return True
    return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter soak logs
        sys.stderr.write("[rest_sim] " + (fmt % args) + "\n")

    def _json(self, code: int, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/_health", "/health"):
            return self._json(200, {"ok": True})
        if not _authorized(self):
            return self._json(401, {"error": "unauthorized"})
        if self.path == "/points/chw_supply_temp":
            return self._json(200, {"value": STATE["chw_st"]})
        if self.path == "/points/plant_kw":
            return self._json(200, {"value": STATE["plant_kw"]})
        if self.path == "/status":
            return self._json(200, {"ok": True, "mode": "sim", "setpoint": STATE["chw_setpoint"]})
        if self.path == "/points/missing_path":
            return self._json(200, {"other": 1})  # no $.value — JSONPath miss
        return self._json(404, {"error": f"unknown path {self.path}"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if self.path == "/_kill":
            self._json(200, {"ok": True, "dying": True})
            # Exit hard so connection drops for circuit-breaker test
            sys.stderr.write("[rest_sim] kill requested — exiting\n")
            os._exit(0)
        if not _authorized(self):
            return self._json(401, {"error": "unauthorized"})
        if self.path == "/points/chw_setpoint":
            try:
                body = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad json"})
            val = body.get("value")
            if val is None:
                return self._json(400, {"error": "missing value"})
            STATE["chw_setpoint"] = float(val)
            STATE["posts"] += 1
            return self._json(200, {"ok": True, "value": STATE["chw_setpoint"], "posts": STATE["posts"]})
        return self._json(404, {"error": f"unknown path {self.path}"})


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(f"[rest_sim] listening on http://{HOST}:{PORT} token_set={bool(TOKEN)}\n")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
