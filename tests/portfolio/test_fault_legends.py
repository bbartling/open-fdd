from portfolio.central.fault_legends import fault_code_hint, short_fault_description


def test_fault_code_hint_prefix():
    assert "Supply air" in fault_code_hint("SAT-FLAT")


def test_short_fault_description_uses_catalog():
    desc = short_fault_description(code="AHU-C")
    assert "Supply air" in desc


def test_short_fault_description_prefers_title():
    desc = short_fault_description(code="VAV-C", title="Zone temp out of band during occupied")
    assert "Zone temp" in desc
