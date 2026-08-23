#!/usr/bin/env python3
"""Deterministic BACpypes3 mini-device for Open-FDD container integration tests.

Modeled on Joel Bender's BACpypes3 mini-device-revisited sample, but kept small
and deterministic for CI.  It exposes the same useful shape: read-only AV/BV
plus commandable AV/BV objects.
"""

import asyncio

from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.app import Application
from bacpypes3.local.analog import AnalogValueObject
from bacpypes3.local.binary import BinaryValueObject
from bacpypes3.local.cmd import Commandable


class CommandableAnalogValueObject(Commandable, AnalogValueObject):
    pass


class CommandableBinaryValueObject(Commandable, BinaryValueObject):
    pass


async def main() -> None:
    args = SimpleArgumentParser().parse_args()
    app = Application.from_args(args)

    read_only_av = AnalogValueObject(
        objectIdentifier=("analogValue", 1),
        objectName="read-only-av",
        presentValue=55.0,
        statusFlags=[0, 0, 0, 0],
        covIncrement=1.0,
        units="degreesFahrenheit",
        description="Open-FDD CI read-only analog value",
    )
    read_only_bv = BinaryValueObject(
        objectIdentifier=("binaryValue", 1),
        objectName="read-only-bv",
        presentValue="active",
        statusFlags=[0, 0, 0, 0],
        description="Open-FDD CI read-only binary value",
    )
    commandable_av = CommandableAnalogValueObject(
        objectIdentifier=("analogValue", 2),
        objectName="commandable-av",
        presentValue=68.0,
        statusFlags=[0, 0, 0, 0],
        covIncrement=1.0,
        units="degreesFahrenheit",
        description="Open-FDD CI commandable analog value",
    )
    commandable_bv = CommandableBinaryValueObject(
        objectIdentifier=("binaryValue", 2),
        objectName="commandable-bv",
        presentValue="inactive",
        statusFlags=[0, 0, 0, 0],
        description="Open-FDD CI commandable binary value",
    )

    for obj in (read_only_av, read_only_bv, commandable_av, commandable_bv):
        app.add_object(obj)

    # Slowly vary the read-only points so repeated polls prove fresh BACnet reads.
    values = [(55.0, "active"), (56.0, "inactive"), (57.0, "active")]
    index = 0
    while True:
        await asyncio.sleep(5.0)
        index = (index + 1) % len(values)
        read_only_av.presentValue, read_only_bv.presentValue = values[index]


if __name__ == "__main__":
    asyncio.run(main())
