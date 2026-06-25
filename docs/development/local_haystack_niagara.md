# Local Niagara nHaystack development

Use this guide to connect Open-FDD to a **local Niagara station** running **nHaystack** for browse/read/model import testing.

## Niagara (high level)

1. Install/enable the **nHaystack** palette on your station.
2. Ensure BACnet devices you care about are exposed as Haystack entities.
3. Note the Haystack REST base URL (commonly `http://<station-host>:<port>/haystack`).
4. Create a station user for Open-FDD (read-only recommended).

External reference (example only): [nHaystack Niagara Pi tutorial](https://github.com/bbartling/py-bacnet-stacks-playground/tree/develop/vibe_code_apps_17/nhaystack-niagara-pi-tutorial).

## Open-FDD configuration

```bash
cp workspace/haystack/local.nhaystack.example.toml workspace/haystack/local.nhaystack.toml
# edit base_url — do not commit this file

export OPENFDD_HAYSTACK_USER="your-station-user"
export OPENFDD_HAYSTACK_PASS="your-station-password"
# optional override:
# export OPENFDD_HAYSTACK_BASE="http://127.0.0.1:8080/haystack"
```

Or set only env vars without a TOML file:

```bash
export OPENFDD_HAYSTACK_BASE="http://127.0.0.1:8080/haystack"
export OPENFDD_HAYSTACK_USER="..."
export OPENFDD_HAYSTACK_PASS="..."
export OPENFDD_HAYSTACK_ENABLED=1
```

## Verify

1. Start Open-FDD locally.
2. Open **Integrations → Haystack** and click **Test connection**.
3. Use **Browse / Nav** and **Read selected** to confirm point ids.
4. **Import model** to populate `/api/model/haystack`.
5. Run `./scripts/openfdd_haystack_smoke.sh` for scripted API checks.

Artifacts are written to `workspace/logs/haystack_smoke_<timestamp>/`.

## Security

- Never commit `local.nhaystack.toml`, passwords, or private IPs.
- Logs redact usernames partially and never print passwords.
- Default driver is **read-only** (no Haystack writes).

## Fixture mode (no live station)

```bash
export OPENFDD_HAYSTACK_FIXTURE=1
```

Uses deterministic demo points for UI/API development and CI unit tests.

## Future parity mapping

Map Haystack point ids to BACnet roles using  
`workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example`  
(5007 roles are **examples only**, not hard-coded in production).

See [haystack_bacnet_parity.md](../validation/haystack_bacnet_parity.md).
