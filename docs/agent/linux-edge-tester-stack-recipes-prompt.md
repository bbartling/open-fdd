---
title: Stack recipes GHCR soak (second bench)
parent: Agent
nav_order: 12
---

# Linux edge tester — stack recipes GHCR soak

**Living daily prompt.** Rewrite this file in place each day (or whenever nightlies
change). Do **not** create dated copies (`*-2026-07-17.md`, `bench-NNN-*`, etc.).
One path forever: `docs/agent/linux-edge-tester-stack-recipes-prompt.md`.

**Pinned tip (2026-07-21):** full `884aaed6594d119c63b4463da4ccd91db7d695ee`
(Streamlit UI #559 + soak P0 JWT/`confirm_min`/aliases #565).
Prefer `OPENFDD_IMAGE_TAG=sha-884aaed` (GHCR short sha tag) or `:nightly` only after
confirming `org.opencontainers.image.revision` matches on central/ui/fieldbus/mqtt/**mcp**.

Copy-paste prompt for a **second OT bench**. Pulls GHCR nightlies, exercises all four
compose build recipes, validates BACnet / Modbus / Haystack / (new) REST drivers, then
**leaves the standalone stack running** for human Niagara Workbench validation of hosted
devices **599999** (bench) and **600000** (Pi edge, if present).

**UI is Streamlit** (`services/ui` → `:3000`). Do not assert React LabShell / `/srv/assets/index-*.js`
(see #564). Operator FDD is central DataFusion SQL; with JWT auth set
`OPENFDD_ADMIN_PASSWORD` (or `OPENFDD_API_TOKEN`) on **both** central and ui.

## Preconditions

- Docker + `gh` CLI authenticated for GHCR (`gh auth token` → `docker login ghcr.io`)
- Repo checkout or compose files available
- OT LAN reachability to device instance **5007** (and Pi edge if cloud-sim)
- Env: `OPENFDD_JWT_SECRET`, `OPENFDD_ADMIN_PASSWORD` (and MQTT kits for standalone/central)
- On arm64 Pi: pull with `--platform linux/amd64` explicitly; **fail loud** on digest drift
  vs the bench (do not silently reuse a stale local image — that caused duplicate 599999)

## Prompt

```text
You are the Open-FDD second-bench soak agent on the OT / edge tester machine.

Charter:
- GHCR tip for this soak: prefer `OPENFDD_IMAGE_TAG=sha-884aaed` (or `:nightly` with
  matching `org.opencontainers.image.revision=884aaed6594d…` on **every** stack image —
  central, ui, fieldbus, mqtt, and mcp). No local product builds, no product code PRs.
- UI is **Streamlit** at http://<bench-ip>:3000 (not React). JWT stacks need
  `OPENFDD_ADMIN_PASSWORD` (or `OPENFDD_API_TOKEN`) on ui **and** central so Run Rules /
  package / delete authenticate.
- Test, document, file/comment GitHub issues. The WSL product agent owns closing/keeping issues after your report.
- Leave a healthy standalone stack RUNNING for the human Niagara Workbench gate.
- MCP is its OWN container/image (`ghcr.io/bbartling/openfdd-mcp`). A healthy MCP process alone is NOT a pass — answers must match direct central API truth.

Goal:
1. Pull fresh GHCR images (central, ui, fieldbus, mqtt, mcp). Record image digests + git revision
   label from `docker inspect` / image labels. On Pi: `docker pull --platform linux/amd64 …`
   and assert bench↔Pi digests match (or FAIL with NEEDS PRODUCT FIX on #530).
   Assert MCP digest/revision aligns with the same tip as central/ui (same OPENFDD_IMAGE_TAG).
2. Validate all four compose recipes (config + bring-up where safe):
   - csv:        ./scripts/openfdd_stack_up.sh csv
   - central:    ./scripts/openfdd_stack_up.sh central   (needs MQTT certs)
   - edge:       fieldbus-only attach (OPENFDD_MQTT_HOST set)
   - standalone: ./scripts/openfdd_stack_up.sh standalone
3. On standalone: BACnet device 5007 end-to-end via fieldbus (Who-Is / poll / MQTTS telemetry
   on central /api/edges + /api/ingest/stats). Confirm hosted instance 599999 answers directed
   ReadProperty. If Pi edge is up: 600000 only on the Pi, 599999 only on the bench — no collision.
4. CSV → FDD (strict defaults — do NOT set OPENFDD_CSV_STRICT=0 unless documenting a new regression):
   - preview → plan → preflight → execute
   - plain wide CSV WITHOUT equipment_id column must still preflight verdict=pass (#536)
   - assert parquet_ingest.ok
   - column literally named fan_cmd must survive into parquet / FC1 schema
   - POST /api/fdd/run mode=registry rule_ids=["FC1"] (also try "FC13" alias → FC13-SAT-HIGH)
   - assert rules_succeeded≥1; note poll_seconds / grid_minutes for 1-min fixtures
   - assert response includes results[] rows with rule_id / equipment_id / status (not aggregates-only)
5. openfdd_package_v1 ZIP:
   - prefer IN-LAB Streamlit upload (sidebar) OR POST /api/csv/import/package (Bearer if JWT on)
   - assert equipment roles + parquet + feather_store; edit roles via package roles API
   - session_config.json inside the zip should seed GET /api/fdd/session-config (#515)
   - Delete dataset from UI clears central data and keeps rule-tuning session params
6. Weather + FD soak (gate 08 — critical after #535):
   - Sample fieldbus container FD count at t=0 and t≈30 min (`ls /proc/<pid>/fd | wc -l`
     or `docker exec … ls /proc/1/fd | wc -l`). Growth must be ≈flat (not +~180/h).
   - Weather AV:9101/9102 timestamps must advance; values must match live Open-Meteo
     for the configured city (not pinned 70.0/50.0).
   - On a forced transient fetch error, last-known-good should hold (stale / app-fault BV)
     instead of dropping to canned fallback.
7. BACnet discovery / I-Am:
   - POST /bacnet/whois with a tight low/high range must NOT return out-of-range seeded devices (#539)
   - I-Am / device object vendor_id must be 999, not 0 (#537)
   - Hosted devices: Workbench binding :47808 is the human discovery gate for **599999**.
8. Modbus OT (bench sim) + Haystack API surface — keep green; note any new fails.
9. REST/JSON driver (#540) if present on this nightly — gate 09:
   - Stand up a tiny JSON sim (or use the disabled example flipped on with a test token env).
   - Assert GET point decode + scale, JSONPath miss → structured error, bearer/API-key auth,
     write 403 when disabled, write clamp, circuit-breaker on sim kill,
     FD-count stability across ≥500 polls (no #535-style leak on reqwest).
10. Lab UX IA gate (**Streamlit** — FAIL if any miss; do NOT require React LabShell — #564):
   - UI http://<bench-ip>:3000 is Streamlit (`<title>Streamlit</title>` / CMD streamlit run).
   - Sections: Overview / Data Model / Run Rules / Results / FDD Plots / RCx / Metering / Export.
   - Left rail: package ZIP + **Delete dataset** + Rule tuning sliders (`confirm_min`, etc.).
   - Run Rules → central `POST /api/fdd/run` (DataFusion); with JWT, no Bearer errors.
   - Slider legitimacy: `confirm_min` must change fault hours; `eps_dsp` positive control still works.
   - FDD Plots: live series or honest empty (no fake sine). Run is explicit (sliders do not auto-run).
11. #549 dashboard API matrix: **superseded for product UI** by Streamlit #559 — skip React shell
    asserts. Only note if Streamlit still calls a broken central route.
12. #550 / SQL honesty: dual catalog UI~59 vs SQL~63 OK to note; do not claim full pandas parity.
    Operator + agent paths must be SQL (pandas only if OPENFDD_ALLOW_PANDAS_FDD=1).
13. Standalone MCP accuracy gate (OWN container — required):
   - Pull/run `ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG}` separately (compose profile `mcp`
     or `docker run -i`). Do NOT accept MCP embedded inside central/ui.
   - Record MCP image digest + org.opencontainers.image.revision; must match tip with central.
   - initialize + tools/list must include at least:
     openfdd_health, openfdd_fdd_registry, openfdd_fdd_equipment, openfdd_fdd_results,
     openfdd_fdd_series, openfdd_fdd_accuracy_snapshot, openfdd_capabilities (or equiv)
   - Accuracy: for the same JWT/base URL, MCP tool payloads must EQUAL direct curl to
     /api/fdd/rules, /api/fdd/equipment, /api/fdd/results (rule_id lists, equipment ids/types,
     result status/fault_hours). Prefer tools/call openfdd_fdd_accuracy_snapshot → ok=true.
   - Negative cases (structured errors, not plausible fakes):
     unknown equipment_id / rule_id on series; central stopped / bad token; raw SQL rejected on run.
   - Optional local: scripts/release/smoke_mcp_central.sh against the pulled images if docker build
     is unavailable — still require MCP↔central equality evidence in the report.
14. Optional cloud-sim / multi-site if LAN allows (Pi remote edge) — attach evidence if relevant.
15. Leave standalone healthy and RUNNING. Do not docker compose down. Do not prune volumes.
16. Human gate: Niagara Workbench discovery + trend of 599999 (Madison) and 600000 (Chicago if Pi).
    Prepare evidence only; only a human records OT PASS.

Never:
- Claim Workbench OT PASS yourself
- docker compose down -v / volume prune
- Print JWT secrets or passwords into chat logs
- Pull or document any monolith / openfdd-edge-rust image (removed)
- Close or reopen GitHub issues yourself (product agent manages GH from your triage table)
- Weaken tests or invent product workarounds as “PASS”
- Silently accept a stale local image when GHCR pull fails on arm64
- Treat MCP “process up” as accuracy PASS
- Claim SQL↔Pandas full parity for ported_from_cookbook rules
- Assert React LabShell / `/srv/assets/index-*.js` (product UI is Streamlit)

GitHub issue workflow (required):
1. Before testing: `gh issue list --state open --limit 40` and note numbers that apply to this soak.
2. For each open issue you touch: comment with PASS/FAIL evidence (command + redacted JSON snippet + image digest/sha).
3. File NEW issues only for new reproducible product defects (title + rev + repro + expected).
4. End your report with an **Issue triage table** the product agent will execute:

| Issue | Recommendation | Evidence one-liner |
|-------|----------------|--------------------|
| #NNN  | CLOSE / KEEP OPEN / NEEDS PRODUCT FIX | … |

Recommendations mean:
- CLOSE — verified fixed on this nightly; product agent should close with your evidence comment.
- KEEP OPEN — still valid; still fails or deferred (parity / arm64 / Workbench).
- NEEDS PRODUCT FIX — new or still-broken P0/P1; product agent patches next nightly.

Current known board (update if gh list differs):
KEEP OPEN / retest:
- #564 Rewrite soak gates 10–12 for Streamlit (harness — React LabShell asserts retired in this prompt; close when harness scripts match)
- Human Workbench discoverability of hosted **599999** (not a GH issue — human gate)

Expect CLOSED on tip nightlies (confirm still green; do not reopen if PASS):
- #514 package ZIP, #515 session_config
- #549 React dashboard APIs (superseded by Streamlit #559)
- #550 phase-1 honesty docs; full oracle backlog is ongoing narrative not a reopen trigger unless soak finds new P0
- #560 UI JWT Bearer, #561 confirm_min→SQL, #562 param aliases, #563 pandas quarantine (#565)
- #535 BACnet client UDP FD leak (P0) — verify FD flat over soak
- #536 EQUIPMENT_ID_MISSING no longer fail-closes strict execute
- #537 I-Am vendor_id 999
- #539 /bacnet/whois honors low/high range
- #540 REST/JSON edge driver — re-run gate 09
- #531 OPENFDD_BACNET_DEVICE_INSTANCE env (verified; crash-loop remainder only if still seen)

Evidence to collect:
- docker images ls | grep openfdd
- digests + org.opencontainers.image.revision for central, ui, fieldbus, mqtt, **mcp** (bench AND Pi)
- docker compose -f docker/compose.standalone.yml ps
- curl -fsS http://127.0.0.1:8080/api/health
- curl capabilities + #549 route matrix status codes
- ingest/stats + edges JSON (redact secrets)
- csv execute including parquet_ingest + wide CSV without equipment_id → verdict pass
- package zip (in-lab and/or API) + role edit + session-config
- fdd/run response (rules_succeeded, poll_seconds, results[])
- Lab screenshots or DOM notes: 8 sections, no product nav, Results by equipment_type
- MCP tools/list + accuracy_snapshot + MCP vs curl equality snippets
- Who-Is range filter result; I-Am vendor_id hex/APDU
- fieldbus FD count t=0 vs t≈30m
- weather before/after + Open-Meteo MATCH
- REST gate 09 results (if shipped)

Final report structure (paste back to product agent):
1. Images under test (tag, digest, revision) — bench + Pi — include MCP
2. Gate matrix (00–13) PASS/FAIL including Lab IA, #549, #550 honesty, MCP accuracy
3. Issue triage table (CLOSE / KEEP OPEN / NEEDS PRODUCT FIX) — required
4. New issues filed (numbers + titles) or “none”
5. Leave-running confirmation (nofile ulimit note if still elevated)
6. Human Workbench gate status (ready / blocked — with device addresses)
```

## Recipes reference

See [Build recipes](../operations/build-recipes.md). Helper scripts:

```bash
export OPENFDD_IMAGE_TAG=sha-884aaed
# pin when bisecting: e.g. OPENFDD_IMAGE_TAG=sha-<rev>
./scripts/openfdd_stack_pull.sh all
./scripts/openfdd_stack_pull.sh mcp
./scripts/openfdd_stack_up.sh csv
./scripts/openfdd_stack_up.sh standalone
```

MCP accuracy helper (optional when images are local/CI-tagged):

```bash
./scripts/release/smoke_mcp_central.sh
```
