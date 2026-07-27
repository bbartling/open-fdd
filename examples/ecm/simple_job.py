from open_fdd.ecm_engineering import ECMJob

job = (
    ECMJob("Lincoln Middle School")
    .set_global(
        area_ft2=85000,
        electric_rate=0.145,
        gas_rate=0.92,
    )
    .add_ecm(
        "static_pressure_reset",
        fan_kw=55.9,
        hours=4100,
        baseline_speed=0.82,
        proposed_speed=0.67,
        cost=7500,
    )
    .add_ecm(
        "boiler_reset",
        base_therms=48000,
        base_eff=0.86,
        prop_eff=0.92,
        cost=12000,
    )
)

print(job.save("Lincoln_Middle_School_ECMs.xlsx"))

print(
    job.calc(
        "fan_affinity",
        design_kw=55.9,
        hours=4100,
        baseline_speed_fraction=0.82,
        proposed_speed_fraction=0.67,
    )
)
