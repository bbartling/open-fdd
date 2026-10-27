#!/usr/bin/env python3
"""Minimal HTTP stub for assert_local_stack_after_repin.sh tests."""
from __future__ import annotations

import argparse
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    parser.add_argument("version_json", help="JSON body for GET /api/version")
    args = parser.parse_args()
    version_body = args.version_json.encode()
    health_body = b'{"ok":true,"historian":"timescale","dual_write":false}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/api/health":
                body = health_body
                ctype = "application/json"
            elif self.path == "/api/version":
                body = version_body
                ctype = "application/json"
            elif self.path.startswith("/api/afdd/scheduler/status"):
                self.send_response(401)
                self.end_headers()
                return
            elif self.path == "/":
                body = b"ok"
                ctype = "text/plain"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    signal.signal(signal.SIGTERM, lambda *_: server.shutdown())
    server.serve_forever()


if __name__ == "__main__":
    main()
