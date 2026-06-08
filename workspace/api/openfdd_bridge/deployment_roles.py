"""Log BACnet vs historian ingest roles at bridge startup (reduces operator confusion)."""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def log_bridge_deployment_roles() -> None:
    """Commission owns BACnet RPM reads; bridge only ingests samples.csv → feather."""
    commission_url = os.environ.get("OPENFDD_BACNET_COMMISSION_URL", "").strip()
    ingest_disabled = os.environ.get("OFDD_DISABLE_POLL_WORKER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    _log.info(
        "BACnet field polling (UDP 47808) runs in the commission container/service — not in bridge. "
        "Bridge feather-ingest worker watches workspace/bacnet/polls/samples.csv (or accepts "
        "POST /internal/bacnet/ingest-samples from commission)."
    )
    if commission_url:
        _log.info("Commission agent: %s", commission_url)
    if ingest_disabled:
        _log.warning(
            "OFDD_DISABLE_POLL_WORKER=1 — bridge CSV→feather ingest worker is off; "
            "historian updates depend on commission POST ingest only."
        )
