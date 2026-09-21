---
name: Wave U V2 MQTT ZAP
overview: "Product openfdd-mqtt + provisioner ACL for gate 26; disposable authenticated ZAP AF. Soft-OPEN mqtt-key-mode-tenant-acl + zap-af-authenticated."
todos:
  - id: v2-mqtt-product
    content: Observer/gate use product MQTT image + provisioner ACL; permanent negatives
    status: pending
  - id: v2-zap-af
    content: Disposable candidate AF with auth/me + route coverage; no live hub ActiveScan
    status: pending
  - id: v2-smoke
    content: Tip PR → GHCR → backup/re-pin → smoke only
    status: pending
isProject: false
---

# V2 — Product MQTT ACL + disposable ZAP AF

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)

## Soft-OPEN closed by this cycle

- `mqtt-key-mode-tenant-acl` / `p2c-mqtt-acl-staging` / UA-03 (product broker path)
- `zap-af-authenticated` / `kali-zap-af` / UA-04 (disposable candidate AF)

## Work

1. Gate [`26_security_mqtt_acl.sh`](../../scripts/nightly-ot-bench/26_security_mqtt_acl.sh) / observer: load **product** `openfdd-mqtt` + provisioner-generated ACL (not only `eclipse-mosquitto` fixtures). Keep fixture lint as separate static check.
2. Permanent negatives: fail if product gate uses fixture-only broker when `OPENFDD_MQTT_ACL_EXECUTE=1`.
3. Consolidate ZAP AF onto disposable runner; prove `/api/auth/me` + protected routes; no `admin.jwt` persistence; no live OT-linked hub ActiveScan.
4. Tip PR → GHCR → Railway backup/re-pin → smoke. **No MEGA.**

## Exit

- Gate 26 PASS with product image evidence in stress artifact when EXECUTE=1.
- Disposable AF PASS artifact + Soft-OPEN rows CLOSED or honest PARTIAL with remaining Medium dispositions.
