# Patch cycle HALT — 3.0.28 closure (2026-06-10)

**Status: HALT** — Acme edge at **3.0.27** (`8739132`). Next agent: read `skills/openfdd-edge-deploy-tune/SKILL.md` and open issues below before new work.

## Cycles completed this session

| Rev | PR | Shipped |
|-----|-----|---------|
| 3.0.25 | [#256](https://github.com/bbartling/open-fdd/pull/256) | VAV/AHU FDD bundle, poll-aware flatline, PDF link, duplicate rules cleanup |
| 3.0.26 | [#258](https://github.com/bbartling/open-fdd/pull/258) | OpenWeather OAT cross-check, BACnet override docs, OAT alias script |
| 3.0.27 | [#261](https://github.com/bbartling/open-fdd/pull/261) | Async override `scan-once` (fix commission disconnect) |
| 3.0.28 | [#262](https://github.com/bbartling/open-fdd/pull/262) | Agent skill + halt doc only |

## Acme live state at halt

| Check | Result |
|-------|--------|
| `/health` | **3.0.27**, git `8739132` |
| Poll throughput | **healthy**, keepup **~0.906**, 340 pts / 60 s |
| Poll health | **33/33** devices |
| FDD batch (3 h check-in) | **0 errors**, 4 rules with single-sample flags (low noise) |
| Tuning brief | **0 errors**, **0 watch/disable** recommendations |
| JSON API `web-oat-t` | Scraping (~78 °F, 20 min poll) |
| `oa-t` model alias | Set on `1100-unknown-2` |
| Rules pushed | **12 enabled** incl. `acme-oat-vs-web-spread` |
| Override scans | 33 devices registered; `scan-once` returns `started: true` (3.0.27) |

## Open issues — do not ignore

1. **[#260](https://github.com/bbartling/open-fdd/issues/260)** — GHCR `unknown blob` on commission image (retry workflow)
2. **Override `last_scan_at`** — was stale (2026-06-08); async scan started but full MSTP device scan may take >15 min — monitor after deploy
3. **`acme-zn-t-oob-occupied`** — may flag ~70%+ on longer windows; auto bounds needs Arrow sweep analytics (≥85% gate)
4. **Recovery rates UI** — RTU fan column not mapped in feather (display `—`)
5. **Duplicate local rule stubs** — do not commit untracked copies in `workspace/data/rules_py/`; canonical files only

## Resume checklist

```bash
source infra/ansible/secrets/acme.env.local
source workspace/auth.env.local
# Follow skills/openfdd-edge-deploy-tune/SKILL.md
./infra/ansible/scripts/acme_operational_verify.sh --host "${ACME_SSH_HOST}"
python3 scripts/acme_validate_fdd_bundle.py
```

No further deploy required until next code change on `master`.
