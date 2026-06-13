"""GL36 FC4 PID hunting — excessive control oscillation (Arrow-native, no pandas).

Modes (``cfg["hunting_mode"]``):
- ``command`` (default): single analog output on ``value_column`` (VAV damper/reheat, pump VFD, RTU cooling %).
- ``ahu_os``: multi-signal AHU operating-state bitmap (economizer + fan + heat + cool).
"""

import pyarrow as pa

from open_fdd.arrow_runtime.cookbook import pid_hunting_ahu_os_mask, pid_hunting_command_mask


def _false_mask(table: pa.Table) -> pa.Array:
    return pa.array([False] * table.num_rows, type=pa.bool_())


def apply_faults_arrow(table, cfg, context=None):
    mode = str(cfg.get("hunting_mode") or "command").strip().lower()
    if mode in ("ahu", "ahu_os", "os"):
        return pid_hunting_ahu_os_mask(table, cfg)
    col = str(cfg.get("value_column") or cfg.get("column") or "").strip()
    if col and col not in table.column_names:
        return _false_mask(table)
    return pid_hunting_command_mask(table, cfg, col=col or None)
