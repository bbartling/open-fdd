#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _onboard_cli import fallback_api_key_from_env_files
from open_fdd.desktop.drivers.onboard_driver import run_onboard_scrape
from open_fdd.desktop.storage.connectors import FeatherConnector
from open_fdd.desktop.storage.feather_store import FeatherStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Onboard one-shot smoke ingest to Feather store")
    parser.add_argument("--site-id", default=os.getenv("OFDD_ONBOARD_SITE_ID", "default"))
    parser.add_argument("--feather-root", default=os.getenv("OFDD_FEATHER_ROOT", ""))
    parser.add_argument("--api-key", default=os.getenv("OFDD_ONBOARD_API_KEY", ""))
    args = parser.parse_args()

    api_key = args.api_key.strip() or fallback_api_key_from_env_files()
    if api_key:
        os.environ["OFDD_ONBOARD_API_KEY"] = api_key
    if args.feather_root:
        store = FeatherStore(root=Path(args.feather_root))
    else:
        store = FeatherStore()
    connector = FeatherConnector(store=store)
    out = run_onboard_scrape(store=connector, site_id=args.site_id)
    print(
        {
            "rows": out.rows,
            "source": out.source,
            "metrics": out.metrics or [],
            "storage_ref": out.storage_ref,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
