"""BACpypes3 read_property_multiple with chunking."""

from __future__ import annotations

from bacpypes3.apdu import AbortPDU, ErrorType, PropertyReference
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier


def unwrap_value(property_value):
    if isinstance(property_value, ErrorType):
        return None
    if isinstance(property_value, AnyAtomic):
        property_value = property_value.get_value()
    if hasattr(property_value, "value"):
        return property_value.value
    if isinstance(property_value, (int, float, str, bool, type(None))):
        return property_value
    return str(property_value)


async def read_multiple_chunked(
    app,
    device_address: str,
    objects: dict[str, list[str]],
    *,
    chunk_size: int = 25,
) -> dict[str, object | None]:
    """Returns {object_id_str: present_value or None}."""
    if not objects:
        return {}

    address_obj = Address(device_address)
    obj_items = list(objects.items())
    merged: dict[str, object | None] = {}

    for i in range(0, len(obj_items), chunk_size):
        chunk = obj_items[i : i + chunk_size]
        parameter_list = []
        for obj_id_str, props in chunk:
            obj_id = ObjectIdentifier(obj_id_str)
            parameter_list.append(obj_id)
            prop_ref_list = [PropertyReference(propertyIdentifier=p) for p in props]
            parameter_list.append(prop_ref_list)
        try:
            response = await app.read_property_multiple(address_obj, parameter_list)
            if isinstance(response, AbortPDU):
                for obj_id_str, _props in chunk:
                    merged.setdefault(obj_id_str, None)
                continue
            for res_oid, _res_pid, _res_idx, property_value in response:
                oid_str = f"{res_oid[0]},{res_oid[1]}"
                merged[oid_str] = unwrap_value(property_value)
        except Exception as err:
            import sys

            print(f"RPM error @ {device_address}: {err}", file=sys.stderr)
            for obj_id_str, _props in chunk:
                merged.setdefault(obj_id_str, None)

    return merged
