## 🚀 Getting Started

### Installation

Install `open-fdd` from PyPI:
```bash
pip install open-fdd
```

### Quick Example

```python
import pandas as pd
from open_fdd.air_handling_unit.fault_condition_one import FaultConditionOne

# Sample data
data = {
    "timestamp": pd.date_range(start="2023-01-01", periods=10, freq="15T"),
    "supply_air_temp": [54, 55, 56, 57, 58, 59, 60, 61, 62, 63],
    "return_air_temp": [70, 70, 70, 70, 70, 70, 70, 70, 70, 70],
}
df = pd.DataFrame(data)

# Run fault detection
fault_checker = FaultConditionOne(df)
df_faults = fault_checker.process()
print(df_faults)
```

➡️ **Continue reading:** [Fault Conditions](fault_conditions.md)

---

