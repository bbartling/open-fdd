# Install-methods checklist for the Grok bot (#1567, plus #1552 and #1587 on the same sites)

Run on a real NF site (3.10.x), one Full and one Lite, after the release that contains these changes. Use the NF console and API only: no SSH, no
Tailscale. Do not write to field devices. Redact passwords, tokens, Timescale URLs and site identifiers in everything you report. Record Central
Time timestamps, the NF version and the release tag for each row. Mark each step PASS / FAIL / N/A with one line of evidence.

Get the bundles from the GitHub release: `open-fdd-<version>.zip` (Full), `open-fdd-lite-<version>.zip` (Lite), `SHA256SUMS`.

## 0. Preflight (read-only)

- [ ] `sha256sum -c SHA256SUMS` passes. Unzip each bundle into its own empty folder; `app.json` is at the folder root and has `id`, `name`, `runtime`,
      `options` and no `files` / `hooks` keys; `hooks-update/` has one JSON per hook (Full: weather, fdd, sparql, analytics, schema, history; Lite: open-meteo-weather).
- [ ] `nf_app_sync.py doctor` (method B tool, read-only) reaches the console and logs in. Record what is already installed (`status`).
- [ ] Console reachable from the PC; note whether NF itself can reach a git host and npm (needed for A only).

## A. Git URL (console +Create)

Needs a git repository whose root is the unzipped bundle (an internal or temporary repo; no secrets in it).

- [ ] Console **+Create**: paste the repo URL and a name equal to the app id slug (`open-fdd` / `open-fdd-lite`). Record the exact form fields.
- [ ] The install finishes (status installed), `npm install` ran (Full), the hooks listed under **Edit** match `hooks-update/`.
- [ ] **Configure** shows the options (`timezone`, `weather`, `exporters`, `latitude`, `longitude`, `site`; Full also `engine`, `windowHours`, `timescale`). Record whether
      string options with an empty default are accepted, and whether a blank one is shown as unset.
- [ ] Question to answer and report: does the git URL form accept a branch / ref or subfolder (for example `url#branch`, a path field)? If it does, record the syntax.
- [ ] Private repo: does the form accept credentials or only public URLs? Record.
- [ ] `nf_app_sync.py doctor` against the result: version, hand-edit guard (a git install writes no push manifest, so expect the "no push manifest" WARN),
      hooks. Record every FAIL. Run each hook once and record the run state.
- [ ] Then run method B `install` over the same app (no `--force`). Record whether it stops on "hand-edited files" and what it says.

## B. nf_app_sync (regression)

- [ ] `install` on a clean NF (or after `uninstall`), no `--force`: PASS, verify run succeeds, `doctor` all PASS (WARNs explained).
- [ ] Re-run `install` (no change): no files rewritten that differ, hand-edit guard quiet.

## C. Single hook (NF MCP `deploy_hook` / `manage_app write_file`)

Lite only (Full's `fdd` needs its whole tree).

- [ ] Create an empty app, write `hooks/lib/paging.js`, `hooks/lib/settings.js`, `hooks/open_meteo_weather.js` and the `hooks-update/open-meteo-weather.json` body, restart.
- [ ] Run the hook once: succeeds, three global variables get a sample. Without the two lib files it fails with a clear module error (record the message).

## D. Release zip through an internal git repo

- [ ] Take the unzipped Lite bundle, commit it as the root of a new internal repo, install with method A. Same checks as A for the hooks. Record the time it took
      and whether the NF host needed internet (git host only, npm for Lite is a no-op).

## #1552 on the same sites (weather off / on / exporters)

- [ ] Weather on (default): the weather hook run succeeds; the summary has `exporters`; with NF's BACnet server present, `exporters["bacnet-av"].status` is `ok` and av.1-3 read back.
- [ ] Set the app option `weather` to `false` (console Configure). Run the hook: returns `{skipped: true, reason: "weather disabled"}`; there is **no** outbound request
      (check the NF egress log or firewall counter if available) and no new sample. `doctor` prints `weather disabled` (PASS), not a failure and no "weather coords" line.
- [ ] Full, weather off: run `fdd`. Summary `oat.weather` is `off`; equips with a tagged outside-air sensor report `oat.local`; MECH-OAT-1 and the econ rules run on it; OAT-METEO is skipped. Stale weather
      points are not used (the log says so). Equips with no OA sensor log "skipped: no outside-air temperature (weather disabled)".
- [ ] RCx weekly runtime and mechanical-cooling charts load with weather off and say "equip outdoor-air temperature".
- [ ] Set `weather` back to `true`: next scheduled (or manual) run writes a new sample to the same variables; history continues; `doctor` back to the coordinates check.
- [ ] `exporters` = `none`: only the variables are written, no `/api/v1/bacnet/` call. `exporters` = `bacnet-av` on a NF without BACnet: the run fails AFTER the variables were written, with the reason.

## #1587 on the same sites (time zone of the occupancy schedule)

- [ ] A Full site whose model site has no `tz`, NF Sites has no zone and the host zone is UTC: run `fdd` with no `timezone` option, record `timezones` in the run summary (`source: none`).
- [ ] Set the app option `timezone` to the site's IANA zone, run `fdd` again: `timezones[site].source` is `app option`; the VAV-1 `occ_mode` follows site-local 07:00-17:00 (compare the first
      confirmed fault of a weekday with the occupied start). Across a DST change the local start time does not move.
- [ ] A site whose model carries `tz`: unchanged (`source: model site`) whatever the option says.
- [ ] An invalid option value (not an IANA name): ignored, named in the log.

## Report

One table: step, PASS/FAIL/N/A, evidence. List what the NF docs do not say that you had to find out (git URL ref / subfolder, private repos, option types, app.json options), and
which of #1567 / #1552 / #1587 can close. Open a generic issue (no site identifiers) for every NF-vs-repo mismatch.
