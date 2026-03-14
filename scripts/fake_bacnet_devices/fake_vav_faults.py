#!/usr/bin/env python
"""
Fake VAV Box BACnet Device for GL36 VAV Request Testing
=======================================================

Fault behavior (aligned with data_model.ttl and FDD rules):
- ZoneTemp (Zone_Air_Temperature_Sensor, polled): time-based schedule so faults occur at
  known times. See fault_schedule.py: minute 10-49 = flatline, 50-54 = out-of-bounds.
- Other points: unchanged (commandable or derived) so the device works for e2e.

Deploy on RPi: copy this file and fault_schedule.py to the same directory; run with
  python fake_vav_faults.py --name Zone1VAV --instance 3456790
"""

import asyncio
import logging
import os
import random
import sys

# So fault_schedule.py is found when run from any cwd (e.g. on RPi: copy this file + fault_schedule.py to same dir)
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from fault_schedule import OUT_OF_BOUNDS_VALUE, scheduled_mode

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

        # Scheduled fault: hold last value for flatline (ZoneTemp only, polled)
        self._zt_flatline_value: float | None = None

        asyncio.create_task(self.update_values())

    def _scheduled_zone_temp(self, normal_value: float, zt_obj: AnalogInputObject) -> tuple[float, str]:
        """
        ZoneTemp (polled): use fault_schedule by UTC minute.
        Returns (value, mode_str) with mode_str in {"normal", "flatline", "bounds"}.
        """
        mode = scheduled_mode()
        if mode == "flatline":
            if self._zt_flatline_value is None:
                self._zt_flatline_value = float(zt_obj.presentValue)
            return self._zt_flatline_value, "flatline"
        if mode == "bounds":
            self._zt_flatline_value = None
            return OUT_OF_BOUNDS_VALUE, "bounds"
        self._zt_flatline_value = None
        return normal_value, "normal"

    async def update_values(self):
        while True:
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
            print("=" * 60)
            print(
                "Fake VAV – updating sensor/loop values (scheduled faults on ZoneTemp)"
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

            # --- ZoneTemp (polled): scheduled flatline/bounds for FDD validation ---
            normal_zone_temp = zsp_val + random.uniform(-3.0, 3.0)
            new_zone_temp, mode = self._scheduled_zone_temp(normal_zone_temp, zt)
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
