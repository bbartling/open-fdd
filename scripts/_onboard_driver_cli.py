#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _onboard_cli import fallback_api_key_from_env_files
from open_fdd.desktop.services.ingest_service import IngestService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run desktop onboard ingest through IngestService")
    parser.add_argument("--site-id", default=os.getenv("OFDD_ONBOARD_SITE_ID", "default"))
    parser.add_argument("--api-key", default=os.getenv("OFDD_ONBOARD_API_KEY", ""))
    args = parser.parse_args()

    api_key = args.api_key.strip() or fallback_api_key_from_env_files()
    if not api_key:
        print("Missing API key. Set --api-key or OFDD_ONBOARD_API_KEY.", file=sys.stderr)
        return 1
    os.environ["OFDD_ONBOARD_API_KEY"] = api_key
    out = IngestService().ingest_onboard(site_id=args.site_id)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
