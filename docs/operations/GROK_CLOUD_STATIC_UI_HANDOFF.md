# Cursor cloud agent — static UI waves (Grok closes, Composer writes)

Paste this file into a Cursor cloud agent. You are the implementing agent. Do not use the local GTK Grok Bot clipboard flow. Do not put secrets, lab IDs, or `.env` in commits or chat.

## Roles

- Composer cloud agents write the diffs. One wave per pull request. Open the PR, then watch `gh pr checks` until every required job is green. Fix a red job on the same branch and watch again. Do not merge.
- Grok re-reads `gh pr checks`. Only then `gh pr merge --squash --delete-branch`. In that same turn, check the box for that wave in the checklist below (`- [ ]` becomes `- [x]`) and set the matching todo `status` to `completed` in `/home/ben/.cursor/plans/grok_cloud_ui_handoff_46657107.plan.md` when that file is on the machine. Do not check a box while Actions is still red. Do not start the next wave until the previous PR is merged, the branch is deleted, and the box is checked.
- Do not delete Actions run https://github.com/bbartling/open-fdd/actions/runs/41337446192. Do not delete a failed run that is the only evidence of a still-open bug. Superseded failed or cancelled runs on a branch that now has a green replacement may be deleted.
- Do not retag `698ea2d`. Do not re-pin the owner stack. Do not `docker compose down -v`. Do not start another 4.0.8 publisher.

## Already done

- Master `0dfa112e` (PR 1486). Publisher run 41342471455 succeeded. Web image `sha-0dfa112`.
- Static shell is on master under `services/central/static/product/`, served at `/app/` when `OPENFDD_STATIC_PRODUCT_UI=1`. See `services/central/src/static_product.rs` and `docs/architecture/adr-013-static-product-ui-central.md`.
- You cannot read the Windows NF Bench Viz tree. Match `services/central/static/product/assets/css/bench.css`: radial background, sticky tabs Overview / Charts / Points / Model, no BACnet tab, no Clerk, no CDN script, same-origin `/api` only.

## Checklist (Grok checks a box only after Actions is green and the PR is merged)

- [x] **Wave A.** Cold `fdd_run` schema, publisher order guard, PR 1486, publisher run 41342471455, web image `sha-0dfa112`. Do not retag `698ea2d`. Do not re-pin the live stack.
- [x] **Wave B.** ADR-013 and the `/app/` Bench Viz shell (`services/central/static/product/`, `OPENFDD_STATIC_PRODUCT_UI=1`). Charts and the model tree stay placeholders until Wave C.
- [x] **Frontend source.** PR 1487 moves `frontend/web` to `archive/product-ui/react-spa-v4` (not under `archive/ot-edge/`). Tests that still open `frontend/web` must follow that path. Keep building `openfdd-web` from the archived Dockerfile until Wave F. Merged as 06cb796c (PR 1487).
- [ ] **Wave C.** Model tree and SPARQL (`GET /api/model/ttl`, `POST /api/model/sparql`). Vendor ECharts under `services/central/static/product/assets/vendor/` (no jsDelivr). Carry the old web UI RCx and FDD plot features: same roles, windows, required-plus-optional series, `confirm_min` after a rule update, and the recent-N preview from data already loaded. Draw them in the Bench Viz theme. Do not copy Plotly. Do not change SQL equations. Draft PR 1488 is only the SPARQL box and does not finish this wave.
- [ ] **Wave C pages stay lean.** `index.html` and `tree.html` only link CSS and script modules. Chart code, session, and API calls live in `services/central/static/product/assets/js/` and `assets/css/`. Do not inline a page into one markup, style, and script file.
- [ ] **Wave C agent spec.** In that same PR, add `openfdd_agent_spec/skills/openfdd-static-ui/SKILL.md` (separate HTML, CSS, and JS; ECharts; the RCx and FDD feature list). Point `openfdd-react-spa` at the archived SPA and send new plot work to the static skill. Add one paragraph to `openfdd_agent_spec/AGENTS.md` and `ARCHITECTURE.md`. Do not check Wave C until the spec files are in the PR.
- [ ] **Wave D.** Three schedule cards (model sync, history, AFDD) on existing durable jobs. An earlier unknown chunk holds the cycle checkpoint even when a later chunk is exact.
- [ ] **Wave E.** CSV, admin, synthetic demo, static real-stack smoke. Replace React-only guards with static-asset, role, and no-Node-on-central checks. ZAP and the old-frontend soak stay DEFERRED, not passed.
- [ ] **Wave F.** Remove the `openfdd-web` container from the default portal compose. Central `/app/` is the product UI. Next patch (confirm master; likely 4.0.9). Publish. Keep the last `openfdd-web` image as rollback. Do not drop the volume or the API. Do not re-pin the live stack.
- [x] **Rust pin.** Separate PR, not a UI wave. Product Axum is already 0.8.9 in `Cargo.lock` via `axum = "0.8"`; write `0.8.9` in `services/central/Cargo.toml`. Same-major bumps for `tower-http`, `tokio`, `sqlx`, and `utoipa` where crates.io is newer. Leave the `tonic` 0.12 / Axum 0.7.9 copy until tonic can build on Axum 0.8. Do not edit `archive/`. This does not block Waves C–F. Merged as 0fbb405d (PR 1489).

## Local Linux checkpoints (this host only)

Do not `docker build` central or web here.

- After the archive PR is merge-ready: `npm test` in `archive/product-ui/react-spa-v4` and `python3 scripts/architecture_react_policy_check.py`.
- After Wave C: `cargo test -p openfdd-central static_product::` and one local central process with `OPENFDD_STATIC_PRODUCT_UI=1`. Browser-check `/app/` (tabs, no CDN, no `/api/v1`).
- After Wave D: the new scheduler test only, on a disposable Timescale URL (`timescale` host rewritten to `127.0.0.1`). Do not touch the live volume.
- After Wave E: the static smoke the PR adds, against `127.0.0.1`.
- After Wave F: read-only `./scripts/ghcr_newest_by_created.py`. Record the SHA. Do not re-pin.

## Old frontend, two steps

The Rust pin does not move or retire the frontend. Source archive is the "Frontend source" box. Removing the container from the default compose is the Wave F box.

## Constraints

Timescale-only product path. No Python or Node in the central image. CSP without `unsafe-inline` or `unsafe-eval`. No BACnet, Clerk, or `/api/v1/*`. No building or vendor hardcoded into product selectors.
