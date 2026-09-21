# Test-bed takeover — Open-FDD (Railway hub + local fieldbus)

**Read this first** if you are new to this checkout, machine, or Cursor session.
Prefer in-repo docs over chat memory. This is the operator path for the current
**Wave U** security-first spine (supersedes Wave T).

## Current pins (re-check live before acting)

| Kind | Cite |
|------|------|
| **FQ OPS PINNED** | `3.5.31` / `sha-7b81eb8` · stress `reports/nightly-ot-bench_20260919T195100Z/` · edge **`vim-1`** |
| **Hub smoke tip** (no FQ claim) | `3.5.33` / `sha-3cd3745` · backup `20260919T231221Z` |
| Living Soft-OPEN / tip log | [`BUG_REPORT_WAVE_P.md`](BUG_REPORT_WAVE_P.md) |
| **Active master** | [`WAVE_U_MASTER.md`](WAVE_U_MASTER.md) · [`.cursor/plans/wave_u_security_hardening_master.plan.md`](../../.cursor/plans/wave_u_security_hardening_master.plan.md) |
| Findings child | [`.cursor/plans/security_railway_ot_nessus_assurance.plan.md`](../../.cursor/plans/security_railway_ot_nessus_assurance.plan.md) |
| Agent law | [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) · [`CONTAINER_AGENT.md`](../../openfdd_agent_spec/CONTAINER_AGENT.md) |
| Patch handbook | [`PATCH_CYCLE.md`](PATCH_CYCLE.md) · [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md) |

Confirm hub before any tip work:

```bash
curl -sf https://openfdd-web-production-af99.up.railway.app/api/health \
  | jq -c '{ok,version,edges,ingest_ok,last_ingest_at,multi_tenant}'
# edges ≥ 1, edge id vim-1 via JWT /api/edges — see railway-cli skill for login
```

## Topology (do not invent)

```text
bensbench x86 fieldbus  --MQTTS-->  Railway openfdd-mqtt
                                      |
                                 openfdd-central  <-- JWT REST/SPA
                                      |
                                 openfdd-web (Caddy/nginx)
```

- **Never** local `docker build` of central/web/mqtt/fieldbus on low-RAM hosts — pull GHCR `sha-*`.
- Fieldbus **not** on Railway. Live OT edge id is **`vim-1`** (not local kit `pi-1` unless that is registered).
- One open product PR at a time; squash-merge `--delete-branch`; 0 stale `tip/` / `docs/` remotes.

## Wave U execution order

Follow [`WAVE_U_MASTER.md`](WAVE_U_MASTER.md) (security spine first; many tiny VERSION bumps OK):

1. **U0** master MD + Soft-OPEN inventory + SUPERSEDE prior plans  
2. **U1** evaluator integrity (E01–E08) + CI wire  
3. **U2** MT harness breadth (Burp-class isolation)  
4. **U3** standalone HTTPS + fieldbus management fail-closed  
5. **U4** MQTT key modes + generated tenant ACL  
6. **U5** authenticated ZAP AF on disposable candidate  
7. **U6** Trivy digests + Nessus-pass readiness (real Nessus Soft-OPEN/BLOCKED until licensed scan)  
8. **Interrupt** `acme-fdd-run-hang` whenever it blocks ops  
9. **After spine** S5 → PyPI → SQL twins → **MEGA FQ** `OPENFDD_SECURITY_EXECUTE=1`  

Wave T plans are **SUPERSEDED** — do not play them. Product child detail: `wave_s3_*` / `wave_s4_*` / `wave_s5_*`.

## Tip loop (every product tip)

```bash
gh pr list --state open   # must be empty before starting a tip branch
# … implement + local unit tests (no stack image build) …
gh pr create && # wait CI green (ignore Copilot AI-scan license fail only)
gh pr merge --squash --delete-branch
TIP=$(git rev-parse --short=7 origin/master)
# wait Publish Open-FDD stack; then:
./scripts/check_ghcr_tip_stack.sh "sha-$TIP"   # or --hub-only then fieldbus later
./scripts/railway_central_workspace_backup.sh
# re-pin central → mqtt → web (openfdd-railway-cli skill); EXPECTED_EDGE_ID=vim-1
./scripts/openfdd_fieldbus_railway_up.sh "sha-$TIP"
# smoke or (T3 only) MEGA:
export OPENFDD_API_BASE=https://openfdd-web-production-af99.up.railway.app
export OPENFDD_SECURITY_EXECUTE=1   # T3 FQ only
./scripts/nightly-ot-bench/run_railway_hub_stress.sh
```

Update [`BUG_REPORT_WAVE_P.md`](BUG_REPORT_WAVE_P.md) + `SESSION_LOG` + ops pin on every tip PR.

## Security tools — what to run (and what Burp is for)

### Division of labor (honest)

| Tool | Owns | Does **not** replace |
|------|------|----------------------|
| **Python harness** (`scripts/security/`) | Repeatable **authn / JWT / tenant ACL A/B / role / CSP-CORS / security.txt** evidence → gates **25** / **25b** / **26** | Broad vuln classes (XSS/SQLi/SSRF fuzz), interactive exploration |
| **ZAP baseline** in hub stress | Passive public URL High=0; Medium via `zap_risk_dispositions.json` only | Authenticated active scan (Kali Soft-OPEN `kali-zap-af`) |
| **Burp Suite / human AF** | Exploratory, novel payloads, UI-driven flows, AF when Soft-OPEN Kali window opens | Nightly regression (use harness for that) |

**Target for our product:** the Python suite must **outperform a human Burp session on multi-tenant isolation and JWT/role matrices** — more routes, more A/B canaries, deterministic detectors, CI + FQ gates, no click fatigue. It must **not** claim “better than Burp at everything”; ZAP/Burp/Kali still own active-scan breadth until Soft-OPEN AF lands.

Inventory honesty today (~138 routes): only a minority are `IMPLEMENTED` with suite emission — rest `PLANNED` / `BLOCKED_POLICY`. Wave U **U2** expands IMPLEMENTED on high-value authenticated GETs + foreign deny (session-config / mapping / datasets / analytics) without marking PLANNED as tested.

### Commands (offline first)

```bash
python3 -B -m unittest discover -s tests/security -v
python3 scripts/security/openfdd_security_probe.py --list-suites
python3 scripts/security/openfdd_security_probe.py \
  --config scripts/security/config/example_security_fixtures.json \
  --base-url http://127.0.0.1:18080 \
  --profile isolated_full --dry-run \
  --output-dir reports/security/dry-run-demo
```

Live hub (authorized window only — secrets via Railway env refs, never print):

```bash
export OPENFDD_SECURITY_EXECUTE=1
# fixtures: scripts/security/config/railway_hub_security_fixtures.json
# wired by gates 25/25b inside run_railway_hub_stress.sh
```

Evidence matrix: [`SECURITY_HARNESS_EVIDENCE_3.5.30.md`](SECURITY_HARNESS_EVIDENCE_3.5.30.md) (refresh tip SHA on Wave U tips).  
README: [`scripts/security/README.md`](../../scripts/security/README.md).  
Full Soft-OPEN table: [`WAVE_U_MASTER.md`](WAVE_U_MASTER.md).

## Soft-OPEN that stay Soft-OPEN (do not tip as “done”)

Stage C IdP/MFA · real Nessus assessment (until licensed isolated scan) · local BACnet FEC · `acme-oa-t-dup-reject` catalog noise · historian N-building scale · RDF-authoritative migration. ZAP AF and MQTT ACL are **Wave U U4/U5 tips**, not greenwash CLOSED without evidence.

## Companion diy-bacnet-router lab (bensbench MS/TP)

Shared OT stress trunk for Open-FDD fieldbus / MQTT soaks. **Do not retune baud during Open-FDD work.**

| Item | Cite |
|------|------|
| **Live trunk baud** | **38400** (FEC read-only when attached) |
| Lab-supported (FEC off, dual mini) | 57600 / 76800 / 115200 |
| **Not claimed** | 9600 / 19200 (USB timing — [rusty-bacnet#707](https://github.com/jscott3201/rusty-bacnet/issues/707)) |
| Full matrix evidence | diy-bacnet-router `docs/evidence/CLAUSE9_BAUD_MATRIX_FULL_FEC_OFF_20260920T132700Z/` |
| Tip pin | rusty-bacnet `9e5168c5` (PR https://github.com/bbartling/diy-bacnet-router/pull/73) |
| Maintainer reply + our update | [#707 comment](https://github.com/jscott3201/rusty-bacnet/issues/707#issuecomment-5750151731) |
| Deferred | 19200 `#715` diagnostics delta; 9600 same-chipset controls — not an Open-FDD product gate |

Agent law for that repo: diy-bacnet-router `AGENTS.md` § Lab trunk baud.

## Anti-patterns

- Greenwashing empty SPARQL or PLANNED routes as PASS  
- Mid-wave FQ MEGA  
- Citing older `sha-*` stress for a newer tip  
- Local stack image builds on bensbench  
- Leaving open PRs / feature branches after merge  
- Claiming “100% secure” or “Burp obsolete”
- Chasing 9600/19200 on the Open-FDD stress trunk (hold 38400)
