# Cursor cloud agent — static UI waves (Grok closes, Composer writes)

Paste this file into a Cursor cloud agent. You are the implementing agent. Do not use the local GTK Grok Bot clipboard flow. Do not put secrets, lab IDs, or `.env` in commits or chat.

## Roles

- Composer cloud agents write the diffs. One wave per pull request. Open the PR, then watch `gh pr checks` until every required job is green. Fix a red job on the same branch and watch again. Do not merge.
- Grok re-reads `gh pr checks`. Only then `gh pr merge --squash --delete-branch`. Do not start the next wave until the previous PR is merged and the branch is deleted.
- Do not delete Actions run https://github.com/bbartling/open-fdd/actions/runs/41337446192. Do not delete a failed run that is the only evidence of a still-open bug. Superseded failed or cancelled runs on a branch that now has a green replacement may be deleted.
- Do not retag `698ea2d`. Do not re-pin the owner stack. Do not `docker compose down -v`. Do not start another 4.0.8 publisher.

## Already done

- Master `0dfa112e` (PR 1486). Publisher run 41342471455 succeeded. Web image `sha-0dfa112`.
- Static shell is on master under `services/central/static/product/`, served at `/app/` when `OPENFDD_STATIC_PRODUCT_UI=1`. See `services/central/src/static_product.rs` and `docs/architecture/adr-013-static-product-ui-central.md`.
- You cannot read the Windows NF Bench Viz tree. Match `services/central/static/product/assets/css/bench.css`: radial background, sticky tabs Overview / Charts / Points / Model, no BACnet tab, no Clerk, no CDN script, same-origin `/api` only.

## Checklist (tick in order)

- [ ] **Archive.** PR 1487 (`chore/archive-react-spa-v4`) moves `frontend/web` to `archive/product-ui/react-spa-v4` (not under `archive/ot-edge/`). Tests and CI that still open `frontend/web` must follow that path. Keep building `openfdd-web` from the archived Dockerfile until Wave F. Actions green, then Grok squash-merges and deletes the branch.
- [ ] **Wave C.** Model tree and SPARQL on existing central routes (`GET /api/model/ttl`, `POST /api/model/sparql`). Vendor ECharts under `services/central/static/product/assets/vendor/` (no jsDelivr). Charts, points, and history from Timescale analytics. Do not change SQL equations. One PR. Actions green, then merge and delete the branch.
- [ ] **Wave D.** Three schedule cards (model sync, history, AFDD) on existing durable jobs. Scheduler case: an earlier unknown chunk holds the cycle checkpoint even when a later chunk is exact. One PR. Actions green, then merge and delete the branch.
- [ ] **Wave E.** CSV, admin, synthetic demo, static real-stack smoke. Replace React-only guards with static-asset, role, and no-Node-on-central checks. ZAP and the old-frontend soak stay DEFERRED, not passed. One PR. Actions green, then merge and delete the branch.
- [ ] **Wave F.** Drop `openfdd-web` from the default portal compose. Bump the next patch (confirm master; likely 4.0.9). Publish. Keep a rollback image. Do not drop the API. Do not re-pin the live stack. Actions and the publisher green, then merge and delete the branch.

## Local Linux checkpoints (this host only)

Do not `docker build` central or web here.

- After the archive PR is merge-ready: `npm test` in `archive/product-ui/react-spa-v4` and `python3 scripts/architecture_react_policy_check.py`.
- After Wave C: `cargo test -p openfdd-central static_product::` and one local central process with `OPENFDD_STATIC_PRODUCT_UI=1`. Browser-check `/app/` (tabs, no CDN, no `/api/v1`).
- After Wave D: the new scheduler test only, on a disposable Timescale URL (`timescale` host rewritten to `127.0.0.1`). Do not touch the live volume.
- After Wave E: the static smoke the PR adds, against `127.0.0.1`.
- After Wave F: read-only `./scripts/ghcr_newest_by_created.py`. Record the SHA. Do not re-pin.

## Constraints

Timescale-only product path. No Python or Node in the central image. CSP without `unsafe-inline` or `unsafe-eval`. No BACnet, Clerk, or `/api/v1/*`. No building or vendor hardcoded into product selectors.
