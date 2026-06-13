from portfolio.central.equipment_classify import hvac_bucket, is_ahu, is_vav


def test_hvac_bucket_from_brick_type():
    assert hvac_bucket({"brick_type": "VAV", "name": "Jci Vav 39"}) == "VAV"
    assert hvac_bucket({"brick_type": "AHU", "name": "AHU 01"}) == "AHU"
    assert is_ahu({"brick_type": "AHU", "name": "Rtu 01"}) is True


def test_ahu_from_equipment_id_rtu():
    assert is_ahu({"id": "acme-vm-bbartling-rtu-01", "name": "1100"}) is True
    assert hvac_bucket({"equipment_id": "acme-vm-bbartling-rtu-01"}) == "AHU"


def test_vav_not_zone():
    assert is_vav({"brick_type": "VAV"}) is True
    assert hvac_bucket({"brick_type": "VAV"}) == "VAV"
