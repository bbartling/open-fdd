# WSL Cursor Agent — GitHub Issue Index

**Bench:** `/home/ben/open-fdd` (GHCR pull only) · **Source:** `/home/ben/open-fdd-src` or this repo  
**Umbrella:** [#429](https://github.com/bbartling/open-fdd/issues/429)

## Fix priority (3.2.12 cycle)

| Issue | Pri | Status in 3.2.12 PR |
|-------|-----|---------------------|
| [#466](https://github.com/bbartling/open-fdd/issues/466) | P0 | `active_profile()` honors `OPENFDD_VALIDATION_PROFILE` |
| [#464](https://github.com/bbartling/open-fdd/issues/464) | P0 | MSTP routing persisted; `read_property_routed` poll/read |
| [#467](https://github.com/bbartling/open-fdd/issues/467) | P1 | Persistent `Arc<Mutex<BACnetClient>>` |
| [#465](https://github.com/bbartling/open-fdd/issues/465) | P1 | Bridge→commission proxy (whois/read/discovery) |
| [#469](https://github.com/bbartling/open-fdd/issues/469) | P1 | `auth.env.local` mode 644; handoff merge on partial rotate |
| [#470](https://github.com/bbartling/open-fdd/issues/470) | P1 | `scripts/bench/` restored |

## Bench deploy after `:nightly` publish

```bash
cd /home/ben/open-fdd
NEW_TAG=nightly ./scripts/openfdd_rust_site_update.sh
chmod 644 workspace/auth.env.local
curl -fsS http://127.0.0.1:8080/health | jq '{ok,version,git_sha_short}'
```

## 5007 acceptance gates

```bash
TOK=$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"integrator","password":"..."}' | jq -r .token)
curl -fsS -X POST http://127.0.0.1:8080/api/bacnet/whois \
  -H "Authorization: Bearer $TOK" -d '{"low":5007,"high":5007}'
curl -fsS -X POST http://127.0.0.1:8080/api/bacnet/read \
  -H "Authorization: Bearer $TOK" -d '{"point_id":"bacnet:5007:analog-input:1173"}'
```

## Deep-sleep GHCR watch (product agent)

```bash
./scripts/openfdd_product_ghcr_deep_sleep.sh
```

Posts to #429 on publish success/fail; 30-minute wake interval.
