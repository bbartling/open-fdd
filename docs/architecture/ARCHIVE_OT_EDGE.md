# OT edge archive (fieldbus / MQTTS)

**Status:** Frozen in-repo (Soft-OPEN ≠ FQ).  
**Pin:** `ot-mqtt-fieldbus-last-good-3.6.18`

## Scope

Open-FDD **continues to ship** `openfdd-fieldbus`, `openfdd-mqtt`, and related
Compose profiles in this repository. Wave-NF Soft-OPEN money path is **HTTPS
vendor portals → central `DataProvider` → Timescale**, not a new GitHub repo and
not deletion of OT trees.

## Policy

- No new Soft-OPEN product features on BACnet/MQTTS fieldbus without explicit
  re-qualification.
- Railway slimmer hub: **central + web + Timescale**; fieldbus stays on-prem when
  OT is needed.
- Last known-good OT stack images: tag **`ot-mqtt-fieldbus-last-good-3.6.18`**.

## Links

- [ADR-011: Pluggable DataProvider](adr-011-pluggable-data-provider.md)
- [ADR-010: Timescale hard cutover](adr-010-timescale-hard-cutover.md)
- Checkpoint NF smoke: `scripts/nf/read_sensors.py`
