# TODO 

Highly experimential "grey box" physics concept idea for fault detection. 


## Parameters for the Physical Model
* TODO - experiment if model should be purely `data-driven` or if somesort of hybrid model could be created with something like this below which would require some tuning efforts.

- **tau (Time Constant)**: 
  - `tau = 5.0`
  - In a real-world scenario, tau would need to be tuned based on the specific dynamics of the HVAC system. This could involve using historical data to estimate how quickly the zone air temperature changes in response to outside temperature fluctuations or changes in heating/cooling input. If the zone air temperature changes more slowly in response to outside temperature changes, tau might need to be increased.

- **C (Capacitance)**:
  - `C = 1.0`
  - Represents the thermal capacitance of the system, indicating its ability to store thermal energy. It determines how much heating or cooling power is required to change the zone air temperature. Similarly, C would need to be adjusted to reflect the specific thermal properties of the building and HVAC system. This could be done by analyzing how much energy is required to achieve a certain temperature change. If the building has high thermal inertia (e.g., due to thick walls or large thermal mass), C might need to be increased to reflect this.

- **delta_t (Time Interval)**:
  - `delta_t = 5.0` (minutes)
  - Represents the time step for each iteration of the physical model. Here, it is set to 5 minutes, meaning the model updates every 5 minutes.

### Function Definition

```python
def physical_model(T_in, T_out, S, P, tau, C, delta_t):
    return T_in + delta_t * ((T_out - T_in) / tau + S * P / C)
```
