# Recorded Normal Framework 3.10.11 responses

Each `*.json` is one recorded exchange: `{ id, request: {method, path, body?}, response: {status, contentType, body}, note? }`.
They were captured from a live NF 3.10.11 (single-node, auth off) running simulated points only, then scrubbed:
site, host and tenant names replaced, addresses moved to `192.0.2.0/24`, hardware inventory, license ids and hook
runtime environments removed. Nothing here names a customer, a building or a person.

What reads them:

- `nf-app/dev/nf-real.mjs` builds the dev mock's answers (`platform/info`, layers, error shapes, run shapes) from them.
- `nf-app/tests/nf-real-contract.test.mjs` replays the recorded requests against `nf-app/dev/mock-nf.mjs` and compares
  status, content type and JSON shape (`nf-app/tests/nf-shape.mjs`). It also checks the recordings stay generic.

Behaviours these recordings pin down (the mock follows them):

| Area | Real NF 3.10.11 |
|---|---|
| int64 fields | strings: `pid`, `totalCount`, `invocationCount`, `size` |
| `point/query` | `nextPageToken` always `""`; records carry the REQUESTED layer name; unknown layer or negative page size = empty 400 `application/grpc`; no page size = empty page + total; takes `page_size` / `page_offset` too |
| `point/points` | success needs `layer:"model"` (or another base layer such as `automation`); with no layer, `default` or an unknown layer the call answers `success:true` and applies **nothing**; attrs merge, a missing key is kept, `""` stays as a key |
| `point/data` | `window` is `300s` (`300` is a 400); resampled `ts` are whole seconds, raw `ts` have nine fractional digits; bad uuid = empty 400 grpc; bad window/method/time = empty 400 `text/plain`; unknown uuid = `values: []` |
| hooks | invoke answers `{pid, groups}`; run `results` are keyed by group (`""`) and `{}` unless `include_results=true`; a hook that returns `ok:false` is still `STATE_SUCCESS`; unknown hook = empty 404 |
| `bacnet/readproperty` | `GET` with `device_address.mac` + `port_id`; the reply echoes `property` and the value carries `array:[]`; unknown object or property is an in-band 200 `{error:{errorClass, errorCode}}`; a bad enum name is an empty 400 `text/plain`; addressing by `device_id` alone answered an empty 500 on the recording instance (the mock still serves it) |
| `points/data` | `POST` `{points:[{uuid, values:[{ts, real}]}]}` answers `{success, taskUuid:""}`; a missing or malformed uuid is an empty 400 `application/grpc` |
| errors | bodies are empty; a route NF does not have answers the web console (GET, 200 html) or 405 |
| `apps` | status `STATUS_INSTALLED`; an app that is not installed is a 200 with an empty list |
| `sites` | `sites: []` while `totalCount` still counts the model sites |

Still mock-only (no recording could be made): a successful command write on a driver-backed point (local simulated
objects have no driver), the BACnet priority array read, Timescale and DuckDB history volumes, a long-running hook run
state (`STATE_RUNNING`), multi-layer overlays of one point (the mock keeps one record per layer).

To add a recording: query the live NF, scrub with the rules above, write the file with a unique `id` equal to its
file name, then add a replay to the contract test.
