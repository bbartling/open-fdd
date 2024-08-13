import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults.fault_condition_one import FaultConditionOne
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib import RDF


# Initialize the Brick graph and model
BRICK = Namespace("https://brickschema.org/schema/1.1/Brick#")
BRICKFRAME = Namespace("https://brickschema.org/schema/1.1/BrickFrame#")
brick_graph = Graph()

brick_graph.bind("brick", BRICK)
brick_graph.bind("brickframe", BRICKFRAME)

# Create the Air Handling Unit (AHU) and related sensors in the Brick model
ahu = URIRef("http://example.com/building/AHU1")
duct_static_sensor = URIRef(
    "http://example.com/building/Supply_Air_Static_Pressure_Sensor"
)
vfd_speed_sensor = URIRef("http://example.com/building/Supply_Fan_VFD_Speed_Sensor")
static_pressure_setpoint = URIRef(
    "http://example.com/building/Static_Pressure_Setpoint"
)

brick_graph.add((ahu, RDF.type, BRICK.Air_Handler_Unit))
brick_graph.add((duct_static_sensor, RDF.type, BRICK.Supply_Air_Static_Pressure_Sensor))
brick_graph.add((vfd_speed_sensor, RDF.type, BRICK.Supply_Fan_VFD_Speed_Sensor))
brick_graph.add((static_pressure_setpoint, RDF.type, BRICK.Static_Pressure_Setpoint))
brick_graph.add((ahu, BRICKFRAME.hasPoint, duct_static_sensor))
brick_graph.add((ahu, BRICKFRAME.hasPoint, vfd_speed_sensor))
brick_graph.add((ahu, BRICKFRAME.hasPoint, static_pressure_setpoint))

# Mapping from URIs to DataFrame column names
column_mapping = {
    str(duct_static_sensor): "duct_static",
    str(vfd_speed_sensor): "supply_vfd_speed",
    str(static_pressure_setpoint): "duct_static_setpoint",
}

# Initialize FaultConditionOne with Brick model and column mapping
fc1 = FaultConditionOne(
    brick_graph,
    column_mapping=column_mapping,
    troubleshoot_mode=False,
    rolling_window_size=5,
)


class TestNoFault:

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            "duct_static": [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
            "duct_static_setpoint": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            "supply_vfd_speed": [0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc1.apply(self.no_fault_df())
        actual = results["fc1_flag"].sum()
        expected = 0
        message = f"FC1 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFault:

    def fault_df(self) -> pd.DataFrame:
        data = {
            "duct_static": [
                0.7,
                0.7,
                0.6,
                0.7,
                0.65,
                0.55,
                0.99,
                0.99,
                0.6,
                0.7,
                0.65,
                0.55,
                0.6,
                0.7,
                0.65,
                0.55,
                0.6,
            ],
            "duct_static_setpoint": [
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
            ],
            "supply_vfd_speed": [
                0.99,
                0.95,
                0.96,
                0.97,
                0.98,
                0.98,
                0.5,
                0.55,
                0.96,
                0.97,
                0.98,
                0.98,
                0.96,
                0.97,
                0.98,
                0.98,
                0.96,
            ],
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc1.apply(self.fault_df())
        actual = results["fc1_flag"].sum()

        expected = 3 + 4
        message = f"FC1 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            "duct_static": [0.8] * 6,
            "duct_static_setpoint": [1.0] * 6,
            "supply_vfd_speed": [99] * 6,
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err("supply_vfd_speed"),
        ):
            fc1.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            "duct_static": [0.8] * 6,
            "duct_static_setpoint": [1.0] * 6,
            "supply_vfd_speed": [99.0] * 6,
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err("supply_vfd_speed"),
        ):
            fc1.apply(self.fault_df_on_output_greater_than_one())
