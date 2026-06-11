"""Cloud exporter loop — poll bridge, POST JSON to webhook/PostBin-style endpoint."""

from __future__ import annotations

import argparse
import logging
import sys
import time

import httpx

from .client import build_payload, post_payload
from .config import ExporterConfig

_log = logging.getLogger("openfdd.cloud_exporter")


def run_once(cfg: ExporterConfig | None = None) -> dict:
    cfg = cfg or ExporterConfig.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with httpx.Client() as client:
        payload = build_payload(client, cfg)
        result = post_payload(client, cfg, payload)
        _log.info("export result: %s", {k: v for k, v in result.items() if k != "error"})
        return result


def run_loop(cfg: ExporterConfig | None = None) -> None:
    cfg = cfg or ExporterConfig.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    backoff = cfg.interval_seconds
    while True:
        try:
            run_once(cfg)
            backoff = cfg.interval_seconds
        except Exception:
            _log.exception("export cycle failed")
            backoff = min(backoff * 2, 3600)
        time.sleep(backoff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open-FDD cloud exporter sidecar")
    parser.add_argument("--once", action="store_true", help="Run one export cycle and exit")
    args = parser.parse_args(argv)
    if args.once:
        result = run_once()
        return 0 if result.get("ok") else 1
    run_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
