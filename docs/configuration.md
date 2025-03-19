## ⚙️ Configuration Dictionary (`config_dict`)

The `config_dict` maps dataset column names to HVAC components (e.g., sensors, dampers, valves) and includes **tuning parameters** for fault detection algorithms.

| Parameter | Description | Default Value |
|-----------|------------|--------------|
| `DELTA_OS_MAX` | Max allowable AHU mode changes per hour before hunting is flagged | `7` |
| `AHU_MIN_OA_DPR` | Minimum outside air damper position (0-1 scale) | `0.2` (20%) |
| `ROLLING_WINDOW_SIZE` | Number of consecutive faults required to trigger flag | `5` |

For more details, see [Configuration Dictionary](configuration.md).

➡️ **Next:** [API Reference](api_reference.md)

