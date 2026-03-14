#!/usr/bin/env python
"""
Fake AHU BACnet Device for GL36 Trim & Respond Testing
======================================================

This script creates a fake AHU BACnet/IP device using BACpypes3.

Fault behavior (aligned with data_model.ttl polled points and FDD rules):
- SA-T (Supply_Air_Temperature_Sensor, polled): time-based schedule so faults occur at
  known times. See fault_schedule.py: minute 10-49 = flatline, 50-54 = out-of-bounds.
- RA-T, MA-T (polled): same schedule so flatline/bounds rules can fire on them too.
- All other analog inputs: generic random so the device looks alive; not used for FDD in test bench.

Deploy on RPi: copy this file and fault_schedule.py to the same directory; run with
  python fake_ahu_faults.py --name BensFakeAhu --instance 3456789
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
    AnalogValueObject,
    AnalogInputObject,
    AnalogOutputObject,
)
from bacpypes3.local.binary import BinaryInputObject, BinaryOutputObject
from bacpypes3.local.cmd import Commandable
from bacpypes3.object import MultiStateValueObject

UPDATE_INTERVAL_SECONDS = 5


class CommandableAnalogValueObject(Commandable, AnalogValueObject):
    """Commandable Analog Value Object"""


class CommandableMultiStateValueObject(Commandable, MultiStateValueObject):
    """Commandable Multi-State Value Object"""


class FakeAHUApplication:
    def __init__(self, args):
        self.app = Application.from_args(args)

        # AHU-level BACnet objects (no VAV points in this device)
        self.points = {
            # ------------- Analog Inputs (Sensors) -------------
            "DAP-P": AnalogInputObject(
                objectIdentifier=("analogInput", 1),
                objectName="DAP-P",
                presentValue=1.0,
                units="inchesOfWater",
                description="AHU Duct Static Pressure",
            ),
            "SA-T": AnalogInputObject(
                objectIdentifier=("analogInput", 2),
                objectName="SA-T",
                presentValue=55.0,
                units="degreesFahrenheit",
                description="Supply Air Temperature",
            ),
            "MA-T": AnalogInputObject(
                objectIdentifier=("analogInput", 3),
                objectName="MA-T",
                presentValue=70.0,
                units="degreesFahrenheit",
                description="Mixed Air Temperature",
            ),
            "RA-T": AnalogInputObject(
                objectIdentifier=("analogInput", 4),
                objectName="RA-T",
                presentValue=72.0,
                units="degreesFahrenheit",
                description="Return Air Temperature",
            ),
            "SA-FLOW": AnalogInputObject(
                objectIdentifier=("analogInput", 5),
                objectName="SA-FLOW",
                presentValue=10000.0,
                units="cubicFeetPerMinute",
                description="Supply Airflow",
            ),
            "OA-T": AnalogInputObject(
                objectIdentifier=("analogInput", 6),
                objectName="OA-T",
                presentValue=60.0,
                units="degreesFahrenheit",
                description="Outside Air Temperature (Local Sensor)",
            ),
            "ELEC-PWR": AnalogInputObject(
                objectIdentifier=("analogInput", 7),
                objectName="ELEC-PWR",
                presentValue=150.0,
                units="kilowatts",
                description="Building Electrical Power",
            ),
            # ------------- Analog Outputs (Commands) -------------
            "SF-O": AnalogOutputObject(
                objectIdentifier=("analogOutput", 1),
                objectName="SF-O",
                presentValue=50.0,
                units="percent",
                covIncrement=1.0,
                description="Supply Fan Speed Command",
            ),
            "HTG-O": AnalogOutputObject(
                objectIdentifier=("analogOutput", 2),
                objectName="HTG-O",
                presentValue=0.0,
                units="percent",
                covIncrement=1.0,
                description="Heating Valve Command",
            ),
            "CLG-O": AnalogOutputObject(
                objectIdentifier=("analogOutput", 3),
                objectName="CLG-O",
                presentValue=0.0,
                units="percent",
                covIncrement=1.0,
                description="Cooling Valve Command",
            ),
            "DPR-O": AnalogOutputObject(
                objectIdentifier=("analogOutput", 4),
                objectName="DPR-O",
                presentValue=0.0,
                units="percent",
                covIncrement=1.0,
                description="Mixing Dampers Command",
            ),
            # ------------- Analog Values (Setpoints) -------------
            "DAP-SP": CommandableAnalogValueObject(
                objectIdentifier=("analogValue", 1),
                objectName="DAP-SP",
                presentValue=1.0,  # in. w.c.
                units="inchesOfWater",
                covIncrement=0.01,
                description="Duct Static Pressure Setpoint (DischargeAirPressureSp)",
            ),
            "SAT-SP": CommandableAnalogValueObject(
                objectIdentifier=("analogValue", 2),
                objectName="SAT-SP",
                presentValue=55.0,
                units="degreesFahrenheit",
                covIncrement=0.1,
                description="Supply Air Temperature Setpoint (DischargeAirTempSp)",
            ),
            "OAT-NETWORK": CommandableAnalogValueObject(
                objectIdentifier=("analogValue", 3),
                objectName="OAT-NETWORK",
                presentValue=60.0,
                units="degreesFahrenheit",
                covIncrement=0.1,
                description="Outside Air Temperature (Network / Averaged)",
            ),
            # ------------- Binary Points -------------
            "SF-S": BinaryInputObject(
                objectIdentifier=("binaryInput", 1),
                objectName="SF-S",
                presentValue="active",
                description="Supply Fan Status",
            ),
            "SF-C": BinaryOutputObject(
                objectIdentifier=("binaryOutput", 1),
                objectName="SF-C",
                presentValue="inactive",
                description="Supply Fan Command (fanRunCmd)",
            ),
            # ------------- Multi-State (Occupancy Schedule) -------------
            "Occ-Schedule": CommandableMultiStateValueObject(
                objectIdentifier=("multiStateValue", 1),
                objectName="Occ-Schedule",
                presentValue=1,  # 1 = Occupied
                numberOfStates=4,
                stateText=["Not Set", "Occupied", "UnOccupied", "Standby"],
                description="Occupancy Schedule State",
            ),
        }

        for obj in self.points.values():
            self.app.add_object(obj)

        # Scheduled fault state: hold last value for flatline (per polled point)
        self._flatline_value: dict[str, float] = {}  # point_name -> stuck value

        asyncio.create_task(self.update_values())

    def _scheduled_sensor_value(
        self, point_name: str, normal_value: float, obj: AnalogInputObject
    ) -> tuple[float, str]:
        """
        For polled sensors (SA-T, RA-T, MA-T): use fault_schedule by UTC minute.
        Returns (value, mode_str) with mode_str in {"normal", "flatline", "bounds"}.
        """
        mode = scheduled_mode()
        if mode == "flatline":
            if point_name not in self._flatline_value:
                self._flatline_value[point_name] = float(obj.presentValue)
            return self._flatline_value[point_name], "flatline"
        if mode == "bounds":
            self._flatline_value.pop(point_name, None)
            return OUT_OF_BOUNDS_VALUE, "bounds"
        self._flatline_value.pop(point_name, None)
        return normal_value, "normal"

    async def update_values(self):
        """
        Simulate changing sensor values.
        Polled points (SA-T, RA-T, MA-T) follow fault_schedule; other analogs are generic random.
        Commandable points (SPs, outputs, schedule) are left alone so Niagara / GL36 can drive them.
        """
        while True:
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
            print("=" * 60)
            print("Fake AHU – updating sensor values (scheduled faults on SA-T, RA-T, MA-T)")

            for name, obj in self.points.items():
                if isinstance(obj, AnalogInputObject):
                    # Polled points (data_model.ttl): scheduled flatline/bounds for FDD validation
                    if name in ("SA-T", "RA-T", "MA-T"):
                        normal = random.uniform(53.0, 72.0) if name == "SA-T" else random.uniform(65.0, 75.0)
                        value, mode = self._scheduled_sensor_value(name, normal, obj)
                        obj.presentValue = value
                        print(f"AI  {name}: {value:.2f}   ({mode})")
                        continue

                    # Non-polled analogs: generic random so device looks alive
                    if name == "ELEC-PWR":
                        normal = random.uniform(120.0, 300.0)
                    elif name == "DAP-P":
                        normal = random.uniform(0.3, 1.5)
                    elif name == "OA-T":
                        normal = random.uniform(30.0, 95.0)
                    elif name == "SA-FLOW":
                        normal = random.uniform(8000.0, 12000.0)
                    else:
                        normal = random.uniform(40.0, 80.0)

                    obj.presentValue = normal
                    print(f"AI  {name}: {normal:.2f}")

                elif isinstance(obj, BinaryInputObject):
                    new_value = random.choice(["active", "inactive"])
                    obj.presentValue = new_value
                    print(f"BI  {name}: {new_value}")

                else:
                    # Print current commandable/outputs without changing them
                    try:
                        pv = obj.presentValue
                    except AttributeError:
                        pv = "<no presentValue>"
                    print(f"CMD {name}: {pv}")


async def main():
    logging.basicConfig(level=logging.INFO)
    args = SimpleArgumentParser().parse_args()
    logging.info("args: %r", args)

    FakeAHUApplication(args)
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("BACnet AHU simulation stopped.")
