#!/usr/bin/env python
"""
Fake AHU BACnet Device for GL36 Trim & Respond Testing
======================================================

This script creates a fake AHU BACnet/IP device using BACpypes3.

Fault Injection Added:
- SA-T occasional flatline (stuck value long enough to trip window-based flatline rules)
- SA-T occasional spike (out-of-bounds value to trip bounds rules)

Usage:
    python fake_ahu.py --name BensFakeAhu --instance 3456789 [--debug]
"""

import asyncio
import logging
import random

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

        # -------------------------------
        # Fault injection state + knobs
        # -------------------------------
        self._fault = {
            "sa_t_flatline_remaining": 0,
            "sa_t_flatline_value": None,
            "sa_t_spike_remaining": 0,
        }

        # With UPDATE_INTERVAL_SECONDS=5 and flatline window=40,
        # you want >= 40 updates stuck => >= 200 seconds.
        self.SAT_FLATLINE_CHANCE_PER_UPDATE = 0.02  # 2% chance each update
        self.SAT_FLATLINE_UPDATES = 45  # >= 40, reliably trips

        self.SAT_SPIKE_CHANCE_PER_UPDATE = 0.01  # 1% chance each update
        self.SAT_SPIKE_UPDATES = 2  # brief spikes

        asyncio.create_task(self.update_values())

    def _maybe_start_sa_t_faults(self, sa_t_obj: AnalogInputObject):
        # Start flatline?
        if self._fault["sa_t_flatline_remaining"] <= 0:
            if random.random() < self.SAT_FLATLINE_CHANCE_PER_UPDATE:
                self._fault["sa_t_flatline_remaining"] = self.SAT_FLATLINE_UPDATES
                self._fault["sa_t_flatline_value"] = float(sa_t_obj.presentValue)

        # Start spike?
        if self._fault["sa_t_spike_remaining"] <= 0:
            if random.random() < self.SAT_SPIKE_CHANCE_PER_UPDATE:
                self._fault["sa_t_spike_remaining"] = self.SAT_SPIKE_UPDATES

    def _apply_sa_t_behavior(self, normal_value: float) -> tuple[float, str]:
        """
        Returns: (value, mode_str)
        mode_str in {"normal","flatline","spike"}
        """
        # Flatline takes priority over spike (so it can complete and trip window faults)
        if self._fault["sa_t_flatline_remaining"] > 0:
            self._fault["sa_t_flatline_remaining"] -= 1
            return float(self._fault["sa_t_flatline_value"]), "flatline"

        if self._fault["sa_t_spike_remaining"] > 0:
            self._fault["sa_t_spike_remaining"] -= 1
            # sensor_bounds.yaml SAT bounds are [40,150], so push out of bounds
            return 180.0, "spike"

        return normal_value, "normal"

    async def update_values(self):
        """
        Simulate changing sensor values.
        Commandable points (SPs, outputs, schedule) are left alone so Niagara / GL36 can drive them.
        """
        while True:
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
            print("=" * 60)
            print("Fake AHU – updating sensor values (with fault injection on SA-T)")

            for name, obj in self.points.items():
                if isinstance(obj, AnalogInputObject):
                    # Normal behavior
                    if name == "ELEC-PWR":
                        normal = random.uniform(120.0, 300.0)
                        obj.presentValue = normal
                        print(f"AI  {name}: {normal:.2f}")
                        continue

                    if name == "SA-T":
                        # Determine whether to start a fault
                        self._maybe_start_sa_t_faults(obj)

                        normal = random.uniform(53.0, 60.0)
                        value, mode = self._apply_sa_t_behavior(normal)

                        obj.presentValue = value
                        print(f"AI  {name}: {value:.2f}   ({mode})")
                        continue

                    if name == "DAP-P":
                        normal = random.uniform(0.3, 1.5)
                    elif name == "OA-T":
                        normal = random.uniform(30.0, 95.0)
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
