# Streamlit UI — ARCHIVED (P2-M6 / Prompt 7)

**Status:** Not a production product UI. React (`frontend/web` + `docker/compose.react.yml`) is the sole shipping UI.

**Last product commit before archive:** `99ccdd9` (P2-M5) / React default flip `e28e156` (P2-M4).

**Recovery (immutable release, not active twin):**

```bash
# Historical GHCR image (pin digest from your registry retention)
docker pull ghcr.io/bbartling/openfdd-ui:nightly

# Optional legacy compose profile (not default):
docker compose -f docker/compose.central.yml --profile streamlit-legacy up -d
```

**Retained in-tree:** source under `services/ui/` for oracle/characterization and emergency recovery reference. Do not wire into default product compose or required CI product gates.

**Preserved separately:** `open_fdd/{rules,analytics,reporting,ecm_engineering}`, `tools/react_parity/**`.
