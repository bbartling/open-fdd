"""
Platform layer: ingest drivers (BACnet, weather, CSV) and headless CLIs.

Driver implementations live in ``open_fdd.platform.drivers``. The desktop bridge
and ``open_fdd.desktop`` services import from there; ``open_fdd.desktop.drivers``
remains as thin compatibility shims.
"""
