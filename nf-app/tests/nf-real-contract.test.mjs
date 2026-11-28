// Contract tests: the dev mock NF (nf-app/dev/mock-nf.mjs) against responses RECORDED from a real Normal Framework
// 3.10.11 (nf-app/tests/fixtures/nf-real/*.json). Each recording is {id, request, response:{status, contentType, body}}.
// The recordings are generic: no site names, hosts or secrets (the hygiene test below guards that), so CI keeps
// checking the mock against real NF behaviour with no live NF around.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { shapeProblems } from "./nf-shape.mjs";

const MOCK = fileURLToPath(new URL("../dev/mock-nf.mjs", import.meta.url));
const FIX = fileURLToPath(new URL("./fixtures/nf-real/", import.meta.url));
const fx = (id) => JSON.parse(fs.readFileSync(path.join(FIX, `${id}.json`), "utf8"));
const ZERO = "00000000-0000-0000-0000-000000000000";

const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer();
  s.once("error", reject);
  s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
});
async function startMock(env = {}) {
  const port = await freePort();
  const child = spawn(process.execPath, [MOCK, String(port)], { stdio: ["ignore", "pipe", "inherit"], env: { ...process.env, MOCK_NOW: "2026-11-18T20:00:00Z", ...env } });
  await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (c) => reject(new Error("mock exited " + c)));
    child.stdout.on("data", (d) => { if (String(d).includes("mock NF:")) resolve(); });
  });
  return { base: `http://127.0.0.1:${port}`, stop: () => { child.removeAllListeners("exit"); child.kill(); } };
}
const send = async (m, method, p, body) => {
  const r = await fetch(m.base + p, { method, headers: body === undefined ? {} : { "Content-Type": "application/json" }, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body) });
  const text = await r.text();
  const ct = (r.headers.get("content-type") || "").split(";")[0];
  return { status: r.status, ct, text, json: ct === "application/json" ? JSON.parse(text) : null };
};
/** Replay recording `id` against the mock with its recorded request (body optionally replaced). */
const replay = (m, id, body) => { const { request } = fx(id); return send(m, request.method, request.path, body !== undefined ? body : request.body); };
const problems = (got, id, opts) => shapeProblems(got, fx(id).response.body, opts);

let real, plain;
before(async () => { real = await startMock({ MOCK_PROFILE: "real-nf" }); plain = await startMock(); });
after(() => { real.stop(); plain.stop(); });

// ---------------------------------------------------------------------------------------------- recordings
test("recordings: well-formed and generic (no hosts, secrets, tenant ids or machine data)", () => {
  const files = fs.readdirSync(FIX).filter((f) => f.endsWith(".json"));
  assert.ok(files.length >= 60, `expected the full recording set, found ${files.length}`);
  for (const f of files) {
    const text = fs.readFileSync(path.join(FIX, f), "utf8");
    const rec = JSON.parse(text);
    assert.equal(rec.id, f.replace(/\.json$/, ""), `${f}: id matches the file name`);
    assert.ok(rec.request && rec.request.method && rec.request.path, `${f}: request`);
    assert.ok(rec.response && Number.isInteger(rec.response.status) && "body" in rec.response, `${f}: response`);
    for (const ip of text.match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g) || []) {
      assert.ok(ip === "127.0.0.1" || ip.startsWith("192.0.2."), `${f}: only loopback and documentation addresses allowed, found ${ip}`);
    }
    assert.ok(!/\.(local|lan|internal|corp)\b/i.test(text.replace(/[a-z0-9-]+\.(?:local)\.[a-z]+/gi, "")), `${f}: no private hostnames`);
    assert.ok(!/[\w.+-]+@[\w-]+\.[\w.-]+/.test(text), `${f}: no email addresses`);
    assert.ok(!/desktop|NF_CLIENT|Bearer\s|ghp_|-----BEGIN/i.test(text), `${f}: no host names or credentials`);
    for (const m of text.matchAll(/"(clientSecret|clientId)":\s*"([^"]*)"/g)) assert.equal(m[2], "<redacted>", `${f}: ${m[1]} redacted`);
    for (const m of text.matchAll(/org_[A-Za-z0-9]+/g)) assert.equal(m[0], "org_EXAMPLE", `${f}: tenant id scrubbed`);
  }
  const info = fx("platform__info").response.body;
  assert.equal(info.machineInfo, "", "hardware inventory blob removed");
  assert.equal(info.siteName, "Example Site");
  assert.equal(info.license.instanceId, ZERO);
});

// ---------------------------------------------------------------------------------------------- platform / sites / bacnet
test("platform/info: real keys and types in both profiles; the real-nf profile is the recording", async () => {
  for (const m of [real, plain]) {
    const r = await replay(m, "platform__info");
    assert.equal(r.status, 200);
    assert.deepEqual(problems(r.json, "platform__info", { optional: ["timezone"] }), []);
  }
  assert.equal((await replay(real, "platform__info")).json.version, "3.10.11-6");
  assert.equal((await replay(real, "platform__info")).json.timezone, "Etc/UTC", "the container zone, not a site zone");
  assert.equal((await replay(plain, "platform__info")).json.timezone, undefined);
});

test("sites: real-nf lists none but totalCount still counts the model sites", async () => {
  const rec = fx("sites__list").response.body;
  assert.deepEqual(rec.sites, []);
  assert.notEqual(rec.totalCount, "0");
  const r = (await replay(real, "sites__list")).json;
  assert.deepEqual(r.sites, []);
  assert.equal(typeof r.totalCount, "string");
  assert.notEqual(r.totalCount, "0");
});

test("bacnet configuration, ports and local objects have NF's shape", async () => {
  assert.deepEqual(problems((await replay(real, "bacnet__configuration")).json, "bacnet__configuration"), []);
  assert.deepEqual(problems((await replay(plain, "bacnet__configuration")).json, "bacnet__configuration"), []);
  assert.deepEqual(problems((await replay(real, "bacnet__ports")).json, "bacnet__ports", { optional: ["ip", "virtual"] }), []);
  assert.deepEqual(problems((await replay(real, "bacnet__local_objects")).json, "bacnet__local_objects"), []);
});

test("equipment/classes answers like NF without a page size: an empty list and the total as a string", async () => {
  const r = await replay(real, "equipment__classes");
  assert.equal(r.status, 200);
  assert.deepEqual(problems(r.json, "equipment__classes"), []);
});

test("schedules: an unknown id is an empty 404 (application/grpc); the list pages with a string totalCount", async () => {
  const miss = await replay(real, "schedules__unknown_id");
  assert.equal(miss.status, 404);
  assert.equal(miss.ct, "application/grpc");
  assert.equal(miss.text, "");
  const list = await send(real, "GET", "/api/v1/schedules?pageSize=1&pageOffset=0");
  assert.equal(list.status, 200);
  assert.equal(typeof list.json.totalCount, "string");
});

// ---------------------------------------------------------------------------------------------- point/query
test("point/query: every field NF sends, the requested layer name, totalCount a string, nextPageToken always empty", async () => {
  // The mock has no automation points of its own: write one the way NF would take it, so the layer page has a record.
  await send(real, "POST", "/api/v1/point/points", { points: [{ uuid: "11111111-1111-4111-8111-111111111111", name: "contract/a", layer: "automation", attrs: { type: "fdd-result" } }] });
  for (const id of ["point_query__default_layer_page", "point_query__automation_layer_page", "point_query__model_layer_page_a", "point_query__model_layer_page_b"]) {
    const rec = fx(id);
    const r = await replay(real, id, { ...rec.request.body, pageSize: 3 });
    assert.equal(r.status, 200, id);
    assert.ok(r.json.points.length > 0, `${id}: mock has points in layer ${rec.request.body.layer}`);
    assert.deepEqual(problems(r.json, id, { optional: ["hpldata", "latestValue", "nextPageToken"] }), [], id);   // one recording was trimmed of its empty nextPageToken
    assert.ok(r.json.points.every((p) => p.layer === rec.request.body.layer), `${id}: records carry the requested layer name`);
    assert.equal(r.json.nextPageToken, "");
  }
});

test("point/query: a driver-backed point's latestValue is {ts, double}; units and writability are enum names", async () => {
  const rec = fx("point_query__bacnet_backed_point_default").response.body.points[0];
  assert.deepEqual(shapeProblems(rec.latestValue, rec.latestValue), []);
  const r = await send(real, "POST", "/api/v1/point/query", { layer: "default", pageSize: 500 });
  const withValue = r.json.points.find((p) => p.latestValue);
  assert.ok(withValue, "mock has points with data");
  assert.deepEqual(shapeProblems(withValue.latestValue, rec.latestValue), []);
  assert.match(withValue.writability, /^WRITABILITY_/);
  assert.match(withValue.units, /^[A-Z_]+$/);
});

test("point/query: no page size is an empty page with the total; paging past the end is empty; both layers' totals are strings", async () => {
  const none = await replay(real, "point_query__no_page_size");
  assert.deepEqual(none.json.points, []);
  assert.equal(typeof none.json.totalCount, "string");
  assert.notEqual(none.json.totalCount, "0");
  const beyond = await replay(real, "point_query__offset_beyond_total");
  assert.deepEqual(beyond.json.points, []);
  assert.ok(Number(beyond.json.totalCount) > 0);
  const miss = await replay(real, "point_query__site_field_no_match");
  assert.deepEqual(miss.json, { points: [], totalCount: "0", nextPageToken: "" });
});

test("point/query: NF takes snake_case paging and ignores fields it does not know", async () => {
  const snake = await replay(real, "point_query__snake_case_paging", { layer: "model", page_size: 1, page_offset: 0 });
  assert.equal(snake.json.points.length, 1);
  const unknown = await replay(real, "point_query__unknown_field", { layer: "model", pageSize: 1, bogus: 1 });
  assert.equal(unknown.status, 200);
});

test("errors: an unknown layer or negative page size is an EMPTY 400 application/grpc; bad JSON an empty 400 text/plain", async () => {
  for (const id of ["errors__query_unknown_layer", "errors__query_negative_page_size"]) {
    const rec = fx(id).response;
    const r = await replay(real, id);
    assert.deepEqual([r.status, r.ct, r.text], [rec.status, rec.contentType, ""], id);
  }
  const bad = await replay(real, "errors__query_bad_json", "{bad");
  assert.deepEqual([bad.status, bad.ct, bad.text], [400, "text/plain", ""]);
});

test("errors: a route NF does not have is the web console (GET, 200 html) or a 405; never a JSON 404", async () => {
  const rec = fx("errors__unknown_get_route_spa_fallback").response;
  assert.equal(rec.status, 200);
  const r = await replay(real, "errors__unknown_get_route_spa_fallback");
  assert.deepEqual([r.status, r.ct], [200, "text/html"]);
  assert.ok(r.text.startsWith(rec.body.$prefix));
  const post = await send(real, "POST", "/api/v2/bacnet/read", { reads: [] });
  assert.equal(post.status, fx("routes__v2_bacnet_read").response.status);
  assert.equal(post.ct, "text/html");
});

// ---------------------------------------------------------------------------------------------- bacnet readproperty / history write
test("bacnet/readproperty: echoes the property, value carries array:[], failures are in-band 200s, a bad enum name is an empty 400", async () => {
  for (const id of ["bacnet__readproperty_device_name", "bacnet__readproperty_device_vendor", "bacnet__readproperty_present_value", "bacnet__readproperty_unknown_property_in_band_error"]) {
    const r = await replay(plain, id);
    assert.equal(r.status, fx(id).response.status, id);
    assert.deepEqual(problems(r.json, id), [], id);
  }
  const bad = await replay(plain, "bacnet__readproperty_bad_property_name");
  assert.deepEqual([bad.status, bad.ct, bad.text], [400, "text/plain", ""]);
  // The unknown-object in-band error has the same shape as the unknown-property one (errorClass/errorCode, no "value").
  const rec = fx("bacnet__readproperty_unknown_object_in_band_error").response.body;
  assert.deepEqual(Object.keys(rec), ["error"]);
  assert.deepEqual(Object.keys(rec.error).sort(), ["errorClass", "errorCode"]);
});

test("points/data: answers {success, taskUuid}; a missing or malformed uuid is an empty 400 grpc", async () => {
  const ok = await replay(plain, "points_data__post_ok");
  assert.equal(ok.status, 200);
  assert.deepEqual(problems(ok.json, "points_data__post_ok"), []);
  for (const id of ["points_data__post_missing_uuid", "points_data__post_malformed_uuid"]) {
    const r = await replay(plain, id);
    assert.deepEqual([r.status, r.ct, r.text], [400, "application/grpc", ""], id);
  }
});

// ---------------------------------------------------------------------------------------------- point/data
async function aPointWithData() {
  const r = await send(real, "POST", "/api/v1/point/query", { layer: "default", pageSize: 500 });
  return r.json.points.find((p) => p.latestValue).uuid;
}
test("point/data: raw samples have nine fractional digits; resampled buckets are whole seconds; shapes match", async () => {
  const uuid = await aPointWithData();
  const raw = await send(real, "GET", `/api/v1/point/data?uuids=${uuid}&count=3&reverse=true`);
  assert.deepEqual(shapeProblems(raw.json, fx("point_data__raw_reverse").response.body), []);
  for (const v of raw.json.data[0].values) assert.match(v.ts, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{9}Z$/);
  const win = await send(real, "GET", `/api/v1/point/data?uuids=${uuid}&count=3&window=300s&method=AVERAGE&reverse=false`);
  assert.deepEqual(shapeProblems(win.json, fx("point_data__window_300s").response.body), []);
  for (const v of win.json.data[0].values) assert.match(v.ts, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
});

test("point/data: no uuids and an unknown uuid are 200 with no values; a malformed uuid is an empty 400 grpc", async () => {
  assert.deepEqual((await replay(real, "point_data__no_uuids")).json, fx("point_data__no_uuids").response.body);
  const unknown = await send(real, "GET", `/api/v1/point/data?uuids=${ZERO}&count=3`);
  assert.deepEqual(unknown.json, fx("point_data__unknown_uuid").response.body);
  const bad = await send(real, "GET", "/api/v1/point/data?uuids=notauuid&count=3");
  const rec = fx("point_data__malformed_uuid").response;
  assert.deepEqual([bad.status, bad.ct, bad.text], [rec.status, rec.contentType, ""]);
});

test("point/data: window is a duration with a unit (300s, not 300), method and times must parse: empty 400 text/plain", async () => {
  const uuid = await aPointWithData();
  for (const q of ["window=300", "window=300s&method=BOGUS", "from=yesterday"]) {
    const r = await send(real, "GET", `/api/v1/point/data?uuids=${uuid}&count=2&${q}`);
    assert.deepEqual([r.status, r.ct, r.text], [400, "text/plain", ""], q);
  }
  for (const id of ["point_data__window_without_unit", "point_data__window_bad_method", "point_data__bad_from"]) assert.equal(fx(id).response.status, 400, `${id} recorded as 400`);
});

// ---------------------------------------------------------------------------------------------- point/points (tag writes)
test("point/points: a record without layer:\"model\" is accepted (success:true) but applies nothing", async () => {
  const uuid = "22222222-2222-4222-8222-222222222222";
  const tagged = async (layer) => (await send(real, "POST", "/api/v1/point/query", { layer, pageSize: 500 })).json.points.find((p) => p.uuid === uuid);
  const none = await send(real, "POST", "/api/v1/point/points", { points: [{ uuid, name: "contract/b", attrs: { contractProbe: "no-layer" } }] });
  assert.equal(none.status, 200);
  assert.deepEqual(shapeProblems(none.json, fx("point_points__post_without_layer").response.body), []);
  assert.equal(none.json.results[0].success, true);
  assert.equal(await tagged("model"), undefined, "nothing applied without a layer");
  for (const layer of ["default", "no-such-layer"]) {
    await send(real, "POST", "/api/v1/point/points", { points: [{ uuid, name: "contract/b", layer, attrs: { contractProbe: layer } }] });
  }
  assert.equal(await tagged("model"), undefined, "the union layer and unknown layers apply nothing either");
  const withLayer = await send(real, "POST", "/api/v1/point/points", { points: [{ uuid, name: "contract/b", layer: "model", attrs: { contractProbe: "with-layer" } }] });
  assert.deepEqual(shapeProblems(withLayer.json, fx("point_points__post_model_layer").response.body), []);
  assert.equal((await tagged("model")).attrs.contractProbe, "with-layer");
  assert.equal((await tagged("default")).attrs.contractProbe, "with-layer", "the union layer shows the model overlay");
  await send(real, "POST", "/api/v1/point/points", { points: [{ uuid, name: "contract/b", layer: "model", attrs: { other: "x" } }] });
  assert.deepEqual((await tagged("model")).attrs, { contractProbe: "with-layer", other: "x" }, "attrs merge; a missing key is kept");
});

// ---------------------------------------------------------------------------------------------- apps and hooks
test("apps: the list entry has every field NF sends; an app that is not installed is an empty list, not a 404", async () => {
  await send(plain, "POST", "/api/v1/_mock/install/state", { files: ["/hooks/a.js"], options: [{ name: "version", value: { string: "5.0.0" } }], hooks: [{ id: "fdd", name: "fdd" }], contents: { "/hooks/a.js": Buffer.from("x").toString("base64") } });
  const list = await send(plain, "GET", "/api/v1/apps");
  const real_app = fx("apps__list").response.body.applications.find((a) => a.id === "open-fdd-lite");
  assert.deepEqual(shapeProblems(list.json.applications[0], real_app, { free: [], ignore: ["hooks", "options"], optional: ["configuration"] }), []);
  assert.equal(list.json.applications[0].status, real_app.status, "STATUS_INSTALLED");
  assert.equal(list.json.totalCount, "1");
  const missing = await replay(plain, "apps__unknown_app");
  assert.deepEqual(missing.json, fx("apps__unknown_app").response.body);
});

test("hooks: invoking answers {pid (string), groups}; an unknown hook is an empty 404 grpc", async () => {
  const run = await replay(real, "hooks__invoke_sparql");
  assert.equal(run.status, 200);
  assert.deepEqual(shapeProblems(run.json, fx("hooks__invoke_sparql").response.body), []);
  assert.equal(typeof run.json.pid, "string");
  const miss = await replay(real, "hooks__invoke_unknown_hook");
  const rec = fx("hooks__invoke_unknown_hook").response;
  assert.deepEqual([miss.status, miss.ct, miss.text], [rec.status, rec.contentType, ""]);
});

test("hooks: runs list newest first with string pids, results {} unless include_results=true, events with timestamps", async () => {
  const path_ = "/api/v1/apps/open-fdd-lite/hooks/sparql";
  await send(real, "POST", path_, { query: "SELECT 1" });
  const second = await send(real, "POST", path_, { query: "SELECT 2" });
  const plainRuns = await send(real, "GET", `${path_}/runs?page_size=1`);
  assert.deepEqual(shapeProblems(plainRuns.json, fx("hook_runs__sparql__without_results").response.body), []);
  assert.deepEqual(plainRuns.json.runs[0].results, {}, "results omitted by default");
  assert.equal(plainRuns.json.runs[0].pid, second.json.pid, "newest first");
  const full = await send(real, "GET", `${path_}/runs?page_size=2&include_results=true&include_logs=true`);
  const rec = fx("hook_runs__sparql__with_results").response.body;
  assert.deepEqual(shapeProblems(full.json, rec), []);
  assert.equal(full.json.runs.length, 2);
  assert.equal(typeof full.json.totalCount, "string");
  assert.match(full.json.runs[0].results[""].events[0].ts, /^\d{4}-\d\d-\d\dT[\d:.]+Z$/);
  assert.equal(full.json.runs[0].state, "STATE_SUCCESS");
});

test("hooks: every recorded last run has NF's run shape (hook results keyed by group, int64 as strings)", () => {
  const files = fs.readdirSync(FIX).filter((f) => /^hook_runs__.*__last\.json$/.test(f));
  assert.ok(files.length >= 8);
  const base = fx("hook_runs__open-fdd-lite__sparql__last").response.body.runs[0];
  for (const f of files) {
    const run = JSON.parse(fs.readFileSync(path.join(FIX, f), "utf8")).response.body.runs[0];
    assert.deepEqual(shapeProblems(run, base, { optional: ["args"], ignore: ["results"] }), [], f);
    assert.equal(typeof run.pid, "string", f);
    assert.ok(["STATE_SUCCESS", "STATE_FAILED", "STATE_RUNNING", "STATE_ENQUEUED", "STATE_SCHEDULED"].includes(run.state), `${f}: ${run.state}`);
  }
});
