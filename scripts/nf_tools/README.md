# NF Haystack tools (generic)

Python 3.10+ standard library only (pytest only for the tests). These tools contain no
site, equipment or point names: you pick everything by tags. Auth works the same way
as `scripts/nf_portal_sensors.py`: the `client_credentials` token goes to
`/api/v1/auth/token`, followed by `/api/v1/point/query` and `/api/v1/point/data`.

## Settings (never printed)
The tools read settings from the environment or from a file passed with `--env-file`
(or the `NF_ENV_FILE` env var). They never look in `private/`.
```
NFURL=https://<installation>.normal-online.net    # or NF_LAN_URL with --via lan
NF_CLIENT_ID=...
NF_CLIENT_SECRET=...
```

| tool | does | writes? |
|---|---|---|
| `nf_model_read.py` | dumps sites, equipment and points (tags, refs, class, unit, markers, period, latest value) | never |
| `nf_query.py latest` / `history` | tag-selected latest values, or history stats / raw samples for a time window | never |
| `nf_tag_apply.py` | shows a model-layer tag diff from a JSON plan, and writes it only with `--apply` | model layer only. Refuses control, conversion and schedule keys, and `period` unless `--set-trend-period` is given. **`--apply` is EXPERIMENTAL** — `POST /api/v1/point/points` is not confirmed in NF docs; dry-run is the default |

Common filters: `--site`, `--equip`, `--equip-tag vav`, `--tags a,b`, `--exclude x`,
`--class/--point-class`, `--format json|csv`, `-o file`. Times: ISO, or a relative value
like `24h`, `7d` or `now`. Naive ISO times are read as box-local.

## Examples (examples only, not defaults)
ACME:
```
python3 nf_model_read.py --env-file ~/.secrets/nf_acme.env --site acme --kind equip --format csv
python3 nf_query.py latest  --env-file ~/.secrets/nf_acme.env --site acme --equip-tag vav --point-class discharge-air-temp-sensor --format csv
python3 nf_query.py history --env-file ~/.secrets/nf_acme.env --site acme --tags cool,pid --from 7d
python3 nf_tag_apply.py     --env-file ~/.secrets/nf_acme.env --site acme plan.json          # dry-run
```
BOSSPI (Ben's Bench):
```
python3 nf_model_read.py --env-file ~/.secrets/nf_bosspi.env --kind site
python3 nf_query.py latest  --env-file ~/.secrets/nf_bosspi.env --site bens-bench --tags temp,sensor --format csv
python3 nf_query.py history --env-file ~/.secrets/nf_bosspi.env --site bens-bench --equip-tag ahu --point-class discharge-air-temp-sensor --from 24h
python3 nf_query.py history --env-file ~/.secrets/nf_bosspi.env --site bens-bench --tags discharge,air,temp --from 24h --raw --format csv -o dat.csv
```
Plan format for `nf_tag_apply.py`: `[{"uuid": "...", "attrs": {"unit": "%", "class": "cool-cmd"}, "period": "300"}]`
(a `null` attr value removes the key).

## Sample output (live, 2026-11-01)
```
$ nf_query.py history --site acme --tags cool,pid --from 7d
{"dis": "RTU-01 Cooling Capacity Status", "class": "cool-cmd", "unit": "%", "n": 1725,
 "min": 0.0, "max": 52.97, "max_ts": "2026-10-28T18:50:00Z", "mean": 3.45, "last": 0.0}
$ nf_model_read.py --site acme --kind equip --format csv     -> 32 records (263 in model layer)
VMA-12,equip,...,"vav,equip,air,hot,water,reheat"
$ nf_query.py history --site bens-bench --equip-tag ahu --point-class discharge-air-temp-sensor --from 24h
{"dis": "Bench Furnace Discharge Air Temp", "unit": "°F", "n": 1441, "min": 0.0,
 "min_ts": "2026-10-31T18:29:18Z", "max": 83.84, "mean": 71.38, "last": 69.32}
```

## Tests
`python3 -m pytest -q tests`. These cover tag and equipment selection, filters, time
parsing, tag-apply guard rails and env-file loading. They are offline.
