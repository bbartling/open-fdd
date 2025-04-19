from typing import Any, Union
from dataclasses import dataclass, field

@dataclass
class InstanceAttribute():
    """
    A class to represent an instance attribute.

    Attributes:
        name (str): The name of the attribute.
        value (Any): The value of the attribute.
        type (Union[float, int, bool, str, None]): The type of the attribute.
        constant_form (str): The constant form of the attribute.
    """

    name: str
    constant_form: str
    description: str
    unit: str
    type: type
    value: Any = None
    required: bool = False

@dataclass
class FaultInputColumn():
    """
    A class to represent a fault input column.

    Attributes:
        name (str): The name of the column.
        value (Any): The value of the column.
        type (Union[float, int, bool, str, None]): The type of the column.
        constant_form (str): The constant form of the column.
    """

    name: str
    constant_form: str
    description: str
    unit: str
    type: type
    value: Any = None
    required: bool = False