# WSL Cursor Agent — GitHub Issue Index

**Bench:** `/home/ben/open-fdd` (GHCR pull only) · **Source:** `/home/ben/open-fdd-src` or this repo  
**Umbrella:** [#429](https://github.com/bbartling/open-fdd/issues/429)

## Fix priority (3.2.13 cycle — PCAP Who-Is storm)

| Issue | Pri | Status in 3.2.13 |
|-------|-----|------------------|
| [#464](https://github.com/bbartling/open-fdd/issues/464) | P0 | Poll **never** broadcasts Who-Is; routed reads from registry |
| [#467](https://github.com/bbartling/open-fdd/issues/467) | P0 | No 0..4194303 discover on poll; `prepare_device_for_poll` only |
| [#465](https://github.com/bbartling/open-fdd/issues/465) | P1 | `OPENFDD_BACNET_COMMISSION_OWNS_POLL=1` — bridge skips poll loop |
| [#466](https://github.com/bbartling/open-fdd/issues/466) | P1 | (3.2.12) profile path — bench verify after PCAP pass |
| [#469](https://github.com/bbartling/open-fdd/issues/469) | P2 | (3.2.12) auth 644 |

**Do not bench-deploy 802258a or 40fecf7** — PCAP FAIL took MSTP network down.

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
