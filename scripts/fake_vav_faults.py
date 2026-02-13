#!/usr/bin/env python
"""
Fake VAV Box BACnet Device for GL36 VAV Request Testing
=======================================================

Fault Injection Added:
- ZoneTemp occasional flatline (stuck long enough to trip window-based flatline rules)
- ZoneTemp occasional spike (out-of-bounds to trip bounds rules)

Usage:
    python fake_vav.py --name Zone1VAV --instance 3456790 [--debug]
"""

import asyncio
import logging
import random

from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.app import Application
from bacpypes3.local.analog import (
    AnalogInputObject,
    AnalogValueObject,
    AnalogOutputObject,
)
from bacpypes3.local.cmd import Commandable

UPDATE_INTERVAL_SECONDS = 20.0


class CommandableAnalogValueObject(Commandable, AnalogValueObject):
    """Commandable Analog Value Object"""


class FakeVAVApplication:
    def __init__(self, args):
        self.app = Application.from_args(args)

        self.points = {
            "ZoneTemp": AnalogInputObject(
                objectIdentifier=("analogInput", 1),
                objectName="ZoneTemp",
                presentValue=72.0,
                units="degreesFahrenheit",
                description="Zone Air Temperature",
            ),
            "VAVFlow": AnalogInputObject(
                objectIdentifier=("analogInput", 2),
                objectName="VAVFlow",
                presentValue=400.0,
                units="cubicFeetPerMinute",
                description="Measured VAV Airflow",
            ),
            "ZoneCoolingSpt": CommandableAnalogValueObject(
                objectIdentifier=("analogValue", 1),
                objectName="ZoneCoolingSpt",
                presentValue=72.0,
                units="degreesFahrenheit",
                covIncrement=0.1,
                description="Zone Cooling Setpoint",
            ),
            "ZoneDemand": CommandableAnalogValueObject(
                objectIdentifier=("analogValue", 2),
                objectName="ZoneDemand",
                presentValue=0.0,
                units="percent",
                covIncrement=1.0,
                description="Cooling Loop Output / Zone Demand (0–100%)",
            ),
            "VAVFlowSpt": CommandableAnalogValueObject(
                objectIdentifier=("analogValue", 3),
                objectName="VAVFlowSpt",
                presentValue=800.0,
                units="cubicFeetPerMinute",
                covIncrement=5.0,
                description="VAV Airflow Setpoint",
            ),
            "VAVDamperCmd": AnalogOutputObject(
                objectIdentifier=("analogOutput", 1),
                objectName="VAVDamperCmd",
                presentValue=50.0,
                units="percent",
                covIncrement=1.0,
                description="VAV Damper Command (%)",
            ),
        }

        for obj in self.points.values():
            self.app.add_object(obj)

        # -------------------------------
        # Fault injection state + knobs
        # -------------------------------
        self._fault = {
            "zt_flatline_remaining": 0,
            "zt_flatline_value": None,
            "zt_spike_remaining": 0,
        }

        # With UPDATE_INTERVAL_SECONDS=20 and flatline window=40,
        # you want >= 40 updates stuck => >= 800 seconds (~13.3 min).
        self.ZT_FLATLINE_CHANCE_PER_UPDATE = 0.03  # 3% chance each update
        self.ZT_FLATLINE_UPDATES = 42  # >= 40, reliably trips

        self.ZT_SPIKE_CHANCE_PER_UPDATE = 0.01  # occasional spikes
        self.ZT_SPIKE_UPDATES = 2  # brief spikes

        asyncio.create_task(self.update_values())

    def _maybe_start_zt_faults(self, zt_obj: AnalogInputObject):
        # Start flatline?
        if self._fault["zt_flatline_remaining"] <= 0:
            if random.random() < self.ZT_FLATLINE_CHANCE_PER_UPDATE:
                self._fault["zt_flatline_remaining"] = self.ZT_FLATLINE_UPDATES
                self._fault["zt_flatline_value"] = float(zt_obj.presentValue)

        # Start spike?
        if self._fault["zt_spike_remaining"] <= 0:
            if random.random() < self.ZT_SPIKE_CHANCE_PER_UPDATE:
                self._fault["zt_spike_remaining"] = self.ZT_SPIKE_UPDATES

    def _apply_zt_behavior(self, normal_value: float) -> tuple[float, str]:
        # Flatline priority
        if self._fault["zt_flatline_remaining"] > 0:
            self._fault["zt_flatline_remaining"] -= 1
            return float(self._fault["zt_flatline_value"]), "flatline"

        if self._fault["zt_spike_remaining"] > 0:
            self._fault["zt_spike_remaining"] -= 1
            # sensor_bounds.yaml zt bounds are [40,100] => push out
            return 120.0, "spike"

        return normal_value, "normal"

    async def update_values(self):
        while True:
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
            print("=" * 60)
            print(
                "Fake VAV – updating sensor/loop values (fault injection on ZoneTemp)"
            )

            zt = self.points["ZoneTemp"]
            zsp = self.points["ZoneCoolingSpt"]
            zd = self.points["ZoneDemand"]
            vf = self.points["VAVFlow"]
            vfsp = self.points["VAVFlowSpt"]
            damper = self.points["VAVDamperCmd"]

            zsp_val = float(zsp.presentValue)
            damper_val = max(0.0, min(100.0, float(damper.presentValue)))
            vfsp_val = max(0.0, float(vfsp.presentValue))
            demand_val = float(zd.presentValue)

            # --- ZoneTemp normal behavior (hover around setpoint) ---
            normal_zone_temp = zsp_val + random.uniform(-3.0, 3.0)

            # maybe start faults + apply
            self._maybe_start_zt_faults(zt)
            new_zone_temp, mode = self._apply_zt_behavior(normal_zone_temp)
            zt.presentValue = new_zone_temp

            # --- ZoneDemand behavior uses the (possibly faulted) zone temp ---
            if new_zone_temp > zsp_val + 1.0:
                demand_val = min(100.0, demand_val + random.uniform(5.0, 15.0))
            elif new_zone_temp < zsp_val - 1.0:
                demand_val = max(0.0, demand_val - random.uniform(5.0, 15.0))
            else:
                if demand_val > 50.0:
                    demand_val -= random.uniform(0.0, 5.0)
                else:
                    demand_val += random.uniform(0.0, 5.0)
            zd.presentValue = demand_val

            # --- VAVFlow: proportional to damper * setpoint + noise ---
            ratio = damper_val / 100.0
            base_flow = vfsp_val * ratio if vfsp_val > 0 else 0.0
            new_flow = max(0.0, base_flow + random.uniform(-50.0, 50.0))
            vf.presentValue = new_flow

            # Print out values
            print(f"ZoneTemp:       {zt.presentValue:.2f} °F   ({mode})")
            print(f"ZoneCoolingSpt: {zsp.presentValue:.2f} °F")
            print(f"ZoneDemand:     {zd.presentValue:.1f} %")
            print(f"VAVFlow:        {vf.presentValue:.1f} cfm")
            print(f"VAVFlowSpt:     {vfsp.presentValue:.1f} cfm")
            print(f"VAVDamperCmd:   {damper.presentValue:.1f} %")


async def main():
    logging.basicConfig(level=logging.INFO)
    args = SimpleArgumentParser().parse_args()
    logging.info("args: %r", args)

    FakeVAVApplication(args)
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("BACnet VAV simulation stopped.")
