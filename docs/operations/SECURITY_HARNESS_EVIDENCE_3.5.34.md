# Security harness evidence — Wave U (3.5.34)

Supersedes tip cites on [`SECURITY_HARNESS_EVIDENCE_3.5.30.md`](SECURITY_HARNESS_EVIDENCE_3.5.30.md) for evaluator integrity.

## U1 evaluator integrity

| Case | Result |
|------|--------|
| E01 all-SKIPPED reconcile | Cannot `fully_qualified` |
| E02 empty `checks[]` | Validator rejects |
| E03 postcheck all-BLOCKED | Rejected via `postcheck=True` |
| E04/E05 empty `{}` own control | FAIL |
| E06 canary in 403 body | FAIL |
| E07 viewer 401 ≠ role deny | FAIL (require 403 after `/me`) |
| E08 ZAP empty `site[]` | Rejected |
| CI | `.github/workflows/appsec.yml` job `security-harness` |

Commands: `python3 -B -m unittest discover -s tests/security -v`

## U2 MT breadth

IMPLEMENTED inventory expanded (fdd/results + rcx/presets own/foreign). Honesty: PLANNED remains untested.

## U3–U6

See [`WAVE_U_MASTER.md`](WAVE_U_MASTER.md) + [`NESSUS_PASS_READINESS.md`](NESSUS_PASS_READINESS.md). Real Nessus assessment Soft-OPEN/BLOCKED until licensed isolated scan.

## Hang interrupt

`STALE_RUNNING_SECS` → 20m; `list_actions` reclaims stale `running` heavy FDD rows (Wave U interrupt for Soft-OPEN `acme-fdd-run-hang`). Root-cause DataFusion/ACME duration Soft-OPEN if still slow after reclaim.
