---
name: "Final GHCR refresh + Grok handoff"
overview: "After all patch PRs merge (except #1102), refresh GHCR tip and hand OT MEGA / issue closeout to Grok."
todos:
  - id: final-merge-audit
    content: "Audit open PRs — only #1102 remains; master green"
    status: pending
  - id: final-wait-publish
    content: "Wait GH Actions stack+MCP+fieldbus publish jobs green on merge commit"
    status: pending
  - id: final-newest
    content: "Pin newest-by-created via scripts/ghcr_newest_by_created.py (not :nightly name sort)"
    status: pending
  - id: final-pull-up
    content: "Prune old digests if needed; openfdd_stack_pull + stack_up --no-pull; demo gate if UI shown"
    status: pending
  - id: final-grok-packet
    content: "Write handoff packet: tip SHA/semver, issue checklist, OT bench commands, do-not-touch #1102"
    status: pending
  - id: final-grok-owns
    content: "Grok runs MEGA/hub stress, closes remaining issues with evidence, no FQ without fully_qualified"
    status: pending
isProject: false
---

# Final — GHCR refresh + Grok handoff

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Models:** orchestrate=`claude-sonnet-5-5-high` · Actions watch=`muse-spark-1.3-high` · post-refresh testing=**Grok bot**

## Preconditions

- PR-01 … PR-13 merged (PR-14 evidence attached or deferred explicitly to Grok)
- [PR #1102](https://github.com/bbartling/open-fdd/pull/1102) still open / untouched
- `master` CI green on tip commit

## Refresh sequence

```bash
# After publish jobs succeed:
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-fieldbus openfdd-mqtt openfdd-mcp
# Pin OPENFDD_IMAGE_TAG=sha-<that>
# prune unused digests if disk tight, then:
./scripts/openfdd_stack_pull.sh react-ot
./scripts/openfdd_stack_up.sh react-ot --no-pull
./scripts/openfdd_demo_gate.sh --ghcr-web   # only if showing published UI
```

## Grok owns after refresh

| Task | Command / note |
| --- | --- |
| Local OT MEGA | `./scripts/nightly-ot-bench/run_all.sh` (or scoped run) |
| Hub stress | `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` when Railway in scope |
| BACnet | gate `02_bacnet_ot` + preflight 47808 |
| Fake Haystack | gate `05_haystack` |
| MT isolation regress | gate `31_wave_n_tenant_acl` |
| MQTTS continuity | gate `32` / `39` for #1070 |
| Close issues | Comment evidence paths; close only with proof |
| Do not | Merge/close #1102; claim FQ if `fully_qualified=false`; wipe volumes |

## Handoff packet template

```text
TIP: <semver>+<shortsha> / sha-<7>
EXCLUDED: PR #1102
MERGED_THIS_WAVE: <list>
OPEN_ISSUES_LEFT: <list or none>
ARTIFACT_ROOT: reports/...
OT_BENCH: BACnet device + fake Haystack on this host
NEXT: Grok MEGA + close issues
```
