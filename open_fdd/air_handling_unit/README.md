# Air Handling Unit (AHU) Fault Detection

## 📌 Overview
This directory contains **fault detection logic** for Variable Volume Air Handling Units (VAV AHUs). The system requires a **configuration dictionary (`config_dict`)** that maps dataset column names to AHU components (e.g., sensors, dampers, valves). The configuration also includes **tuning parameters** for fault detection algorithms.

✅ **Designed for BRICK schema compatibility**  
✅ **Tunable parameters to reduce false positives**  
✅ **Built-in troubleshooting mode for debugging**

---

## 🛠️ Configuration Dictionary (`config_dict`)
The `config_dict` defines sensor column mappings and tuning parameters. Key variables include:

| Parameter | Description | Default Value |
|-----------|------------|--------------|
| `DELTA_OS_MAX` | Max allowable AHU mode changes per hour before hunting is flagged | `7` |
| `AHU_MIN_OA_DPR` | Minimum outside air damper position (0-1 scale) | `0.2` (20%) |
| `OAT_RAT_DELTA_MIN` | Minimum delta between outside and return air for OA fraction calc | `10` |
| `AIRFLOW_ERR_THRES` | Error threshold for airflow discrepancies | `0.3` |
| `AHU_MIN_OA_CFM_DESIGN` | Design minimum outdoor air volume (cfm) | `2500` |
| `ROLLING_WINDOW_SIZE` | Number of consecutive faults required to trigger flag | `5` |

💡 *For further details, see the expanded `config_dict` section below.*

<details>
  <summary>Full Configuration Dictionary</summary>
  
  ```python
  config_dict = {
      'AHU_NAME': "MZVAV_1",
      'INDEX_COL_NAME': "timestamp",
      'DUCT_STATIC_COL': "SaStatic",
      'DUCT_STATIC_SETPOINT_COL': "SaStaticSPt",
      'SUPPLY_VFD_SPEED_COL': "Sa_FanSpeed",
      'MAT_COL': "MA_Temp",
      'OAT_COL': "OaTemp",
      'SAT_COL': "SaTempSP",
      'RAT_COL': "RaTemp",
      'HEATING_SIG_COL': "HW_Valve",  
      'COOLING_SIG_COL': "CW_Valve",  
      'ECONOMIZER_SIG_COL': "OA_Damper",
      'SUPPLY_FAN_AIR_VOLUME_COL': None,  # Optional for Fault Condition 6
      'ROLLING_WINDOW_SIZE': 5
  }
  ```
</details>

---

## 📖 Fault Detection Logic
Each **Fault Condition (FC)** follows ASHRAE and mechanical engineering principles for HVAC fault diagnostics.

### Example: Fault Condition 1 (Low Duct Static Pressure with Fan at Max Speed)
This condition flags a fault if the AHU’s duct static pressure is consistently below the setpoint while the supply fan operates near 100% speed.

$$
\text{DSP} < \text{DPSP} - \text{eDSP} \quad \text{and} \quad \text{VFDSPD} \geq 99\% - \text{eVFDSPD}
$$

```python
# Rolling sum to count consecutive faults
df["combined_check"] = df["static_check_"] & df["fan_check_"]
df["rolling_sum"] = df["combined_check"].rolling(window=config_dict["ROLLING_WINDOW_SIZE"]).sum()
df["fc1_flag"] = (df["rolling_sum"] == config_dict["ROLLING_WINDOW_SIZE"]).astype(int)
```

---

## 🔎 AHU Fault Equations
| Fault Condition | Description |
|-----------------|-------------|
| **FC1** | Duct static pressure too low with fan at max speed |
| **FC2** | Mix temperature too low (should be between OA & RA) |
| **FC3** | Mix temperature too high (should be between OA & RA) |
| **FC4** | AHU PID hunting—too many state changes |
| **FC5** | Supply air temperature too low (should be higher than MA) |
| **FC6** | Outside air fraction incorrect (should match design %) |
| **FC7** | Supply air temperature too low in full heating mode |
| **FC8** | Supply air ≈ Mix air in economizer mode |
| **FC9** | OA temp too high for free cooling (no mech cooling) |
| **FC10** | OA ≈ Mix air in economizer + mech cooling mode |
| **FC11** | OA temp too low for 100% OA cooling |
| **FC12** | Supply air temperature too high (should be lower than MA) |
| **FC13** | Supply air temperature too high in full cooling mode |
| **FC14** | Temperature drop across inactive cooling coil |
| **FC15** | Temperature rise across inactive heating coil |

---

## 🔜 Upcoming Features
✅ **Graphical Visualization:** Improve reporting with plots & dashboards  
✅ **SQL/Grafana Integration:** Store results in time-series databases  
✅ **Energy Efficiency Metrics:** Identify excessive reheat/cooling issues  

💡 *Want a new feature? Post a GitHub Issue or Discussion!*

---

## 📝 Contribute
**How to get involved:**
1. **Clone the repository**:
   ```bash
   git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
   ```
2. **Install dependencies**:
   ```bash
   py -3.12 -m pip install -r requirements.txt
   ```
3. **Run tests**:
   ```bash
   py -3.12 -m pytest
   ```
4. **Submit a Pull Request (PR)** with your changes!

---

## 📜 License
**MIT License** – Open-source and free to use for all.
```text
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software... (standard MIT license text)
```

🚀 *Open-source fault detection for smarter HVAC systems!*

