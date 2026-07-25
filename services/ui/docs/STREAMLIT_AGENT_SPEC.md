# Streamlit UI — agent specification (`services/ui`)

## Mission

Maintain the **single** Open-FDD Streamlit app: vibe19 operator workflows + Jobs + WattLab export handoff. Production FDD is **DataFusion SQL** on central. Pandas stays as the online cookbook / oracle (also tested in the external vibe19 playground).

## Do

- Keep `app/rules/cookbook_catalog.py` (59) readable and importable
- Route operator **Run Rules** through `central_client.run_fdd` (registry SQL)
- Preserve WattLab dump on Export (external vibe20 consumer)
- Preserve Jobs sidebar → `workspace/jobs/`
- Update online cookbooks when rule semantics change

## Do not

- Delete pandas cookbook modules “because SQL exists”
- Reintroduce React dashboard
- Spawn a separate Streamlit app for vibe20 / EnergyPlus
- Claim production pandas FDD without `OPENFDD_ALLOW_PANDAS_FDD=1`
- Weaken CI layout guards in `dashboard_contract.py`

## Open-FDD stack

Images: `openfdd-central`, `openfdd-ui`, `openfdd-fieldbus`, `openfdd-mqtt`, `openfdd-mcp`.  
Docs: [DataFusion-first](../../docs/architecture/datafusion-first.md), [Rule Cookbook](../../docs/rules/cookbook/).
