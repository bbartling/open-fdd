"""Open-FDD for Normal Framework: pull a site from NF and run the pandas reference rules.

    from open_fdd.nf import NFClient, load_model, equipment_frames, run_rules
    client = NFClient.from_env()                     # NF_URL, NF_CLIENT_ID/SECRET, ...
    model = load_model(client)
    frames = equipment_frames(client, model, start, end)   # {(site, equip): SI DataFrame}
    print(run_rules(frames))

``client`` is standard library only; ``model`` / ``rules`` / ``export`` need pandas
(``pip install 'open-fdd[nf]'``); reading Turtle needs rdflib (``'open-fdd[rdf]'``).
"""

from open_fdd.nf.client import NFClient, NFError

__all__ = [
    "NFClient", "NFError", "load_model", "bind_equipment", "equipment_frames", "run_rules",
    "read_csv_export", "csv_frames", "read_turtle",
]


def __getattr__(name):  # lazy: keep ``import open_fdd.nf`` free of pandas
    if name in ("load_model", "bind_equipment", "equipment_frames"):
        from open_fdd.nf import model
        return getattr(model, name)
    if name == "run_rules":
        from open_fdd.nf import rules
        return rules.run_rules
    if name in ("read_csv_export", "csv_frames", "read_turtle"):
        from open_fdd.nf import export
        return getattr(export, name)
    raise AttributeError(name)
