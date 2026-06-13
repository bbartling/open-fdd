# Overnight ACME validation via RCx Central

RCx Central drives read-only validation of the ACME OpenFDD Edge over Tailscale.

## Prerequisites

- Local RCx Central API (`:8060`) and Dash (`:8050`).
- ACME Edge registered under **Edge Connections** with credentials in `portfolio/config/` (gitignored).
- `gh` CLI authenticated for PR/CI inspection.

## Try-out (2 cycles, no sleep)

```bash
OPENFDD_LIVE_ACME=1 \
RCX_CENTRAL_API_URL=http://127.0.0.1:8060 \
RCX_CENTRAL_DASH_URL=http://127.0.0.1:8050 \
RCX_EDGE_SITE=acme \
RCX_PATCH_CYCLES=2 \
RCX_CYCLE_SLEEP_MINUTES=0 \
python3 scripts/rcx_central_overnight_patch_cycle.py
```

## Overnight (10 cycles, 2 h spacing)

Set `RCX_PATCH_CYCLES=10` and `RCX_CYCLE_SLEEP_MINUTES=120`.

Reports land in `reports/rcx_central_overnight_logs/cycle_NN.md`.

## Read-only scope

Collects health, model tree counts, fault status, and overview data. No BACnet writes.
