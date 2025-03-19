## 📖 API Reference

### `FaultCondition`

#### `class open_fdd.air_handling_unit.fault_condition.FaultCondition`
**Base class for fault detection conditions**.

* TODO is a make a complete API reference...!

```python
class FaultCondition:
    def __init__(self, df: pd.DataFrame):
        pass
    def process(self) -> pd.DataFrame:
        """Run fault detection and return DataFrame with results."""
        pass
```

### `FaultConditionOne`

#### `class open_fdd.air_handling_unit.fault_condition_one.FaultConditionOne`
Detects low duct static pressure with max fan speed.

```python
fault_checker = FaultConditionOne(df)
df_faults = fault_checker.process()
```

➡️ **Continue to:** [Example Workflows](examples.md)

