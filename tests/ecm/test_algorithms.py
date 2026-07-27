from open_fdd.ecm_engineering import calculate, crosscheck

def test_fan_affinity():
    result = calculate(
        "fan_affinity",
        {
            "design_kw": 60,
            "hours": 3500,
            "baseline_speed_fraction": 0.80,
            "proposed_speed_fraction": 0.68,
        },
    )
    assert result["savings_kwh"] > 0

def test_boiler():
    result = calculate(
        "boiler_efficiency_improvement",
        {
            "annual_heating_mmbtu": 5000,
            "baseline_efficiency": 0.82,
            "proposed_efficiency": 0.95,
        },
    )
    assert result["savings_therms"] > 0

def test_crosscheck():
    assert crosscheck(100, 110)["verdict"] == "REASONABLE_SCREENING_ALIGNMENT"
