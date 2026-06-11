---
title: Write safety
parent: BACnet
nav_order: 4
---

# Write safety

{: .warning }
> **BACnet writes can change live plant behavior.** Open-FDD disables writes by default. Enable only with operator sign-off, a tested allowlist, and audit logging.

## Defaults

| Control | Default |
|---------|---------|
| Supervisory writes | **Off** |
| Write allowlist | Empty — must enumerate device/object |
| Audit | Commands logged when writes enabled |

## Enable writes (commission role)

1. Set env flag documented in [Security]({% link security/index.md %}) (`OFDD_BACNET_WRITE_ENABLED` or site equivalent).
2. Populate write allowlist CSV / config with explicit object IDs.
3. Use **commission** role JWT; every write should include reason/note where API supports it.
4. Test on bench hardware before production OT.

## Operator rules

- Never write setpoints or overrides on life-safety or fire/smoke interlocks through experimental rules.
- Prefer read-only polling for FDD until rules are validated in Rule Lab.
- Revert overrides through BACnet priority relinquish where supported.
