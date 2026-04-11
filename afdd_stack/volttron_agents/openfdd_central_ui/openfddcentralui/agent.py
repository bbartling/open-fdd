"""
Serve the Open-FDD React production build from the VOLTTRON platform web service.

Requires a web-enabled platform (``bind-web-address`` in ``$VOLTTRON_HOME/config``) and
``VolttronCentral`` / ``VolttronCentralPlatform`` installed per upstream ``vcfg`` docs.
This agent only registers a static path; it does not replace Central.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from volttron.platform.agent import utils
from volttron.platform.vip.agent import Agent, Core

_log = logging.getLogger(__name__)
__version__ = "0.1.0"


def openfdd_central_ui(config_path, **kwargs):
    cfg: dict = {}
    if config_path:
        p = Path(config_path)
        if p.is_file():
            cfg = json.loads(p.read_text(encoding="utf-8"))
    web_root = cfg.get("web_root") or ""
    return OpenfddCentralUi(web_root, **kwargs)


class OpenfddCentralUi(Agent):
    """Registers ``^/openfdd/.*`` → static files (Vite ``dist`` with ``VITE_BASE_PATH=/openfdd``)."""

    def __init__(self, web_root: str, **kwargs):
        kwargs.setdefault("enable_web", True)
        super().__init__(**kwargs)
        self._web_root = Path(web_root).expanduser().resolve() if web_root else None

    @Core.receiver("onstart")
    def _on_start(self, _sender, **_kwargs):
        root = self._web_root
        if not root or not root.is_dir():
            _log.error("openfdd_central_ui: web_root missing or not a directory: %s", root)
            return
        self.vip.web.register_path(r"^/openfdd/.*", str(root))
        _log.info("openfdd_central_ui: static UI at /openfdd/ → %s", root)


def main():
    utils.vip_main(openfdd_central_ui, version=__version__)


if __name__ == "__main__":
    sys.exit(main())
