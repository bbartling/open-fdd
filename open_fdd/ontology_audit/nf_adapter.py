"""Optional: a read-only Turtle snapshot of the site model from an NF box (needs ``open-fdd[nf]`` and NF credentials).

The audit and doctor never import this module unless ``--from-nf`` is used. It only reads the app's ``rdf`` hook.
"""
from __future__ import annotations


def fetch_turtle(*, url: str | None = None, env_file: str | None = None, via: str | None = None,
                 app: str = "full") -> tuple[str, str]:
    """``(turtle, base)`` from the Open-FDD app's ``rdf`` hook (``app="full"`` or ``"lite"``)."""
    from open_fdd.nf.client import NFClient
    from open_fdd.nf.sparql_data import APP_FULL, APP_LITE, hook_transport, rdf_turtle

    client = NFClient(url) if url else NFClient.from_env(via=via, env_file=env_file)
    return rdf_turtle(hook_transport(client, APP_LITE if app == "lite" else APP_FULL))
