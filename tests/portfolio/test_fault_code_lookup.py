from portfolio.central.fault_code_lookup import lookup_fault_description


def test_catalog_codes():
    assert "Supply air" in lookup_fault_description("AHU-C")
    assert "Outdoor" in lookup_fault_description("BLD-B")
    assert lookup_fault_description("VAV-E").startswith("Rogue")


def test_unknown_falls_back_empty():
    assert lookup_fault_description("NOT-A-CODE") == ""
