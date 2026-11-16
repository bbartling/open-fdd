"""Optional: a read-only Turtle snapshot of the site model from an NF box (needs ``open-fdd[nf]`` and NF credentials).

The audit and doctor never import this module unless ``--from-nf`` is used. It only reads the app's ``rdf`` hook.
"""
from __future__ import annotations

import os


def fetch_turtle(*, url: str | None = None, env_file: str | None = None, via: str | None = None,
                 app: str = "full") -> tuple[str, str]:
    """``(turtle, base)`` from the Open-FDD app's ``rdf`` hook (``app="full"`` or ``"lite"``).

    Credentials and ``NF_CA_FILE`` always come from the environment / ``env_file``; ``url`` only overrides the URL.
    Connection or auth errors are raised as ``OSError``.
    """
    from open_fdd.nf.client import NFClient, NFError
    from open_fdd.nf.sparql_data import APP_FULL, APP_LITE, hook_transport, rdf_turtle

    env = dict(os.environ)
    if url:
        env["NF_URL"] = url
        via = None  # NF_URL comes first without a ``via``
    try:
        client = NFClient.from_env(via=via, env_file=env_file, env=env)
        return rdf_turtle(hook_transport(client, APP_LITE if app == "lite" else APP_FULL))
    except NFError as exc:
        raise OSError(f"NF: {exc}") from exc
