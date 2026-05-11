from datetime import date

from openfdd_agent_shell.manifest import Manifest
from openfdd_agent_shell.memory.store import MemoryStore, truncate_bootstrap


def test_truncate_bootstrap():
    text, truncated = truncate_bootstrap("abcdef", 4)
    assert truncated
    assert text.endswith("...")


def test_memory_layout_and_search(repo_root, tmp_path):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", tmp_path)
    store = MemoryStore(manifest)
    store.ensure_layout()
    assert manifest.memory.bootstrap_file.is_file()
    store.append_daily("commissioned site rtu-07")
    store.append_domain("sites", "rtu-07", "SAT column mapped to supply_air_temp")
    hits = store.search("rtu-07")
    assert hits
    block = store.bootstrap_block()
    assert "Workspace memory" in block
    assert store.paths.divergence_file.is_file()
    assert "Working architecture divergence" in block


def test_read_daily_lookback(repo_root, tmp_path):
    manifest = Manifest.load(repo_root / "openfdd.toml.example", tmp_path)
    store = MemoryStore(manifest)
    store.append_daily("older note", day=date.today())
    notes = store.read_daily_notes()
    assert "older note" in notes
