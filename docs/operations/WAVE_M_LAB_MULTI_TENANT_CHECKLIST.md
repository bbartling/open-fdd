# Wave M M3 — Lab multi-tenant enable checklist

Prod stays `multi_tenant=false` until Stage C checklist (M4). This document is the **lab-only** enable harness.

## Refuse silent prod enable

- Do **not** set `OPENFDD_MULTI_TENANT=1` (or equivalent) on the Railway production hub without Stage C sign-off.
- Health must continue to report `"multi_tenant": false` on prod until then.
- Lab / compose / disposable Railway candidates may enable MT for isolation gates.

## Lab enable steps

1. Tip images green (`./scripts/check_ghcr_tip_stack.sh`).
2. Disposable volume or empty workspace (never overwrite prod historian).
3. Set control-plane tenants JSON under workspace; enable mode via documented env only.
4. Run Wave L isolation gates 11–16 against the **lab** candidate.
5. Record evidence paths in BUG_REPORT (lab, not prod pin).

## Harness smoke

```bash
# Lab candidate only — refuse if HUB looks like production pin without waiver
export OPENFDD_MULTI_TENANT=1
# ... start tip compose / disposable candidate ...
curl -sf "$CENTRAL_BASE/api/health" | jq '{version, multi_tenant}'
# Expect multi_tenant=true on lab; prod must remain false.
```

## Exit criteria

- [ ] Lab checklist executed with evidence
- [ ] Prod `/api/health` still `multi_tenant=false`
- [ ] No silent env flip on gleaming-cooperation production
