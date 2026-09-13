---
title: ECM engineering math
parent: ECM
nav_order: 5
---

# ECM engineering calculations (agent + PyPI)

Install: `pip install open-fdd` (optional extras: `[oracle]`, `[analytics]`, `[reporting]`).

Product FDD remains DataFusion on GHCR. This page documents **Python ECM benchmarks** for AI agents and engineers.

## Fan affinity (static pressure reset)

Affinity laws for variable-speed fans (power ∝ speed³ when pressure follows affinity):

$$
P_{\mathrm{prop}} = P_{\mathrm{base}} \left(\frac{N_{\mathrm{prop}}}{N_{\mathrm{base}}}\right)^{3}
$$

$$
\Delta E \approx (P_{\mathrm{base}} - P_{\mathrm{prop}}) \times h
$$

where $$P$$ is fan power (kW), $$N$$ is relative speed (0–1), and $$h$$ is annual hours.

Python:

```python
from open_fdd.ecm_engineering import ECMJob

job = ECMJob("Example School").set_global(electric_rate=0.14)
job.add_ecm(
    "static_pressure_reset",
    fan_kw=55.9,
    hours=4100,
    baseline_speed=0.82,
    proposed_speed=0.67,
)
job.save("example_ecms.xlsx")
```

## Agent skill pointers

| Need | Tool |
|------|------|
| ECM workbook + calcs | PyPI `open_fdd.ecm_engineering` — [`docs/ecm/AGENTS_ECM_ENGINEERING.md`](../ecm/AGENTS_ECM_ENGINEERING.md) |
| Central REST / FDD | `openfdd-mcp` stdio |
| BACnet wire debug (read-only) | [rusty-bacnet-mcp](../mcp-agents/companion-rusty-bacnet-mcp.md) · py-bacnet-stacks-playground (external) |
| OT poll policy | [`BACNET_OT_POLICY.md`](BACNET_OT_POLICY.md) — fieldbus **never** cloud |

## PyPI refresh

When calcs or these docs change: follow [`docs/ecm/PYPI_RELEASE_CHECKLIST.md`](../ecm/PYPI_RELEASE_CHECKLIST.md) and republish Trusted Publishing.
