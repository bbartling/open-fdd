#!/usr/bin/env node
// Contract test suite for the Open-FDD UI API. Runs against any backend:
//
//   node contract/test/run.mjs --base http://127.0.0.1:8790 [--spec openapi/open-fdd-ui-api.yaml]
//                              [--viewer user:pass] [--operator user:pass]
//
// Credentials also come from OFDD_CONTRACT_VIEWER / OFDD_CONTRACT_OPERATOR ("user:pass"); the defaults are the
// mock's dev-only fixture users. Every JSON response is validated against the OpenAPI schema of its operation and
// status; behavioural checks cover capability gating, the auth flow (refresh cookie flags, rotation, logout),
// SI units, pagination and the 400/401/403/404 cases. A write test restores the value it changed.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";
import Ajv2020 from "ajv/dist/2020.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
function creds(name, envName, fallback) {
  const raw = arg(name, process.env[envName] || fallback);
  const i = raw.indexOf(":");
  return { username: raw.slice(0, i), password: raw.slice(i + 1) };
}

const BASE = arg("base", process.env.OFDD_CONTRACT_BASE || "").replace(/\/+$/, "");
if (!BASE) {
  console.error("usage: node contract/test/run.mjs --base http://host:port");
  process.exit(2);
}
const SPEC_PATH = path.resolve(arg("spec", path.join(HERE, "..", "..", "openapi", "open-fdd-ui-api.yaml")));
const VIEWER = creds("viewer", "OFDD_CONTRACT_VIEWER", "viewer:viewer-demo");
const OPERATOR = creds("operator", "OFDD_CONTRACT_OPERATOR", "operator:operator-demo");

// ---- schema ---------------------------------------------------------------------------------------------------
const spec = YAML.parse(fs.readFileSync(SPEC_PATH, "utf8"));
const SCHEMA_ID = "https://open-fdd.invalid/open-fdd-ui-api.json";
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

function rewriteRefs(node) {
  if (Array.isArray(node)) return node.map(rewriteRefs);
  if (!node || typeof node !== "object") return node;
  const out = {};
  for (const [k, v] of Object.entries(node)) {
    out[k] = k === "$ref" && typeof v === "string" ? v.replace(/^#\/components\/schemas\//, `${SCHEMA_ID}#/$defs/`) : rewriteRefs(v);
  }
  return out;
}

const ajv = new Ajv2020({ strict: false, allErrors: true });
ajv.addFormat("date-time", { type: "string", validate: (s) => RFC3339.test(s) && Number.isFinite(Date.parse(s)) });
ajv.addFormat("password", true);
ajv.addSchema({ $id: SCHEMA_ID, $defs: rewriteRefs(spec.components.schemas) });
const validators = new Map();

function resolve(obj) {
  while (obj && obj.$ref) {
    const parts = obj.$ref.replace(/^#\//, "").split("/");
    obj = parts.reduce((o, k) => o[k], spec);
  }
  return obj;
}

/** Validator for a JSON body of (method, path template, status), or null when the spec declares no body. */
function validatorFor(method, template, status) {
  const key = `${method} ${template} ${status}`;
  if (validators.has(key)) return validators.get(key);
  const op = spec.paths[template]?.[method.toLowerCase()];
  assert.ok(op, `spec has no operation ${method} ${template}`);
  const declared = op.responses[String(status)] ?? op.responses.default;
  assert.ok(declared, `${method} ${template}: status ${status} is not declared in the spec`);
  const schema = resolve(declared).content?.["application/json"]?.schema;
  const v = schema ? ajv.compile(rewriteRefs(schema)) : null;
  validators.set(key, v);
  return v;
}

function assertValid(v, data, what) {
  if (!v(data)) assert.fail(`${what} does not match the schema:\n${ajv.errorsText(v.errors, { separator: "\n" })}\n${JSON.stringify(data).slice(0, 600)}`);
}

const errorValidator = ajv.compile({ $ref: `${SCHEMA_ID}#/$defs/Error` });

// ---- HTTP -----------------------------------------------------------------------------------------------------
/**
 * Call the API and validate the response against the spec.
 * @param {string} method
 * @param {string} template  OpenAPI path template, e.g. /api/rules/{rule_id}/confirm_min
 * @param {{params?: Record<string,string>, query?: Record<string,string|number>, token?: string, cookie?: string,
 *          json?: unknown, raw?: string, contentType?: string}} [o]
 */
async function call(method, template, o = {}) {
  let p = template.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(o.params[k]));
  const qs = new URLSearchParams(Object.entries(o.query || {}).map(([k, v]) => [k, String(v)])).toString();
  if (qs) p += `?${qs}`;
  const headers = { Accept: "application/json" };
  if (o.token) headers.Authorization = `Bearer ${o.token}`;
  if (o.cookie) headers.Cookie = o.cookie;
  let body;
  if (o.json !== undefined || o.raw !== undefined) {
    body = o.raw ?? JSON.stringify(o.json);
    headers["Content-Type"] = o.contentType || "application/json";
  }
  const res = await fetch(BASE + p, { method, headers, body, redirect: "manual" });
  const text = await res.text();
  const r = { status: res.status, headers: res.headers, setCookies: res.headers.getSetCookie(), text, json: undefined };
  const what = `${method} ${p} -> ${res.status}`;
  if (res.status === 204) {
    assert.equal(text, "", `${what}: 204 must have no body`);
    return r;
  }
  assert.match(res.headers.get("content-type") || "", /^application\/json\b/i, `${what}: JSON content type`);
  r.json = JSON.parse(text);
  const v = spec.paths[template] ? validatorFor(method, template, res.status) : errorValidator;
  if (v) assertValid(v, r.json, what);
  if (res.status >= 400) assertValid(errorValidator, r.json, `${what} error body`);
  return r;
}

function expectError(r, status, code) {
  assert.equal(r.status, status, `expected ${status} ${code}, got ${r.status} ${r.text.slice(0, 200)}`);
  if (code) assert.equal(r.json.error.code, code);
}

/** Parse one Set-Cookie header into {name, value, attrs (lower-case keys)}. */
function parseCookie(header) {
  const [pair, ...rest] = header.split(";").map((s) => s.trim());
  const i = pair.indexOf("=");
  const attrs = {};
  for (const a of rest) {
    const j = a.indexOf("=");
    attrs[(j < 0 ? a : a.slice(0, j)).toLowerCase()] = j < 0 ? true : a.slice(j + 1);
  }
  return { name: pair.slice(0, i), value: pair.slice(i + 1), attrs };
}

function refreshCookie(r) {
  const c = r.setCookies.map(parseCookie).find((x) => x.name === "ofdd_refresh");
  assert.ok(c, "response sets the ofdd_refresh cookie");
  return c;
}

function assertRefreshCookieFlags(c) {
  assert.equal(c.attrs.httponly, true, "refresh cookie is HttpOnly");
  assert.equal(c.attrs.secure, true, "refresh cookie is Secure");
  assert.equal(String(c.attrs.samesite).toLowerCase(), "strict", "refresh cookie is SameSite=Strict");
  assert.equal(c.attrs.path, "/api/auth", "refresh cookie Path=/api/auth");
}

/** Walk every page of a list endpoint. */
async function all(template, o = {}, limit) {
  const items = [];
  let cursor = null;
  for (let n = 0; n < 10000; n++) {
    const query = { ...(o.query || {}), ...(limit ? { limit } : {}), ...(cursor ? { cursor } : {}) };
    const r = await call("GET", template, { ...o, query });
    assert.equal(r.status, 200, `${template}: ${r.text.slice(0, 200)}`);
    items.push(...r.json.items);
    cursor = r.json.next_cursor;
    if (!cursor) return items;
  }
  assert.fail(`${template}: pagination did not end`);
}

// ---- state ----------------------------------------------------------------------------------------------------
let meta;
let caps;
let viewerToken;   // undefined when the host does not use /api/auth
let operatorToken;
let points = [];
let win = { from: "", to: "" };

const iso = (ms) => new Date(ms).toISOString();
const BOGUS_TOKEN = ["contract", "test", "bogus"].join("-");

async function login(c) {
  const r = await call("POST", "/api/auth/login", { json: c });
  assert.equal(r.status, 200, `login as ${c.username}: ${r.text.slice(0, 200)}`);
  return r;
}

before(async () => {
  const r = await call("GET", "/api/meta");
  assert.equal(r.status, 200);
  meta = r.json;
  caps = meta.capabilities;
  if (caps.auth) {
    viewerToken = (await login(VIEWER)).json.access_token;
    operatorToken = (await login(OPERATOR)).json.access_token;
  }
  points = await all("/api/points", { token: viewerToken });
  const last = Math.max(...points.map((p) => (p.last_sample_time ? Date.parse(p.last_sample_time) : -Infinity)));
  const end = Number.isFinite(last) ? last + 60_000 : Date.now();
  win = { from: iso(end - 3 * 86_400_000), to: iso(end) };
});

// ---- meta -----------------------------------------------------------------------------------------------------
test("meta: contract major version matches the spec, capability flags are booleans", () => {
  const [specMajor] = spec.info.version.split(".");
  assert.equal(meta.contract_version.split(".")[0], specMajor, `host implements ${meta.contract_version}, spec is ${spec.info.version}`);
  for (const k of ["rules_write", "export_csv", "export_parquet", "sparql", "auth"]) assert.equal(typeof caps[k], "boolean", k);
});

test("meta is public (no token needed)", async () => {
  const r = await call("GET", "/api/meta");
  assert.equal(r.status, 200);
});

test("unknown endpoint: 404 with an error body", async () => {
  const r = await call("GET", "/api/contract-test-no-such-endpoint", { token: viewerToken });
  expectError(r, 404, "not_found");
});

// ---- auth -----------------------------------------------------------------------------------------------------
test("auth off: /api/auth/* answer 404 and data needs no bearer token", async (t) => {
  if (caps.auth) return t.skip("host authenticates through /api/auth");
  expectError(await call("POST", "/api/auth/login", { json: VIEWER }), 404, "not_found");
  assert.equal((await call("GET", "/api/equipment")).status, 200);
});

test("auth: data endpoints need a valid bearer token (401 + WWW-Authenticate)", async (t) => {
  if (!caps.auth) return t.skip("auth capability is off");
  for (const [tpl, query] of [["/api/equipment", {}], ["/api/points", {}], ["/api/rules", {}],
    ["/api/results", win], ["/api/samples", { point: points[0]?.id || "x", ...win }]]) {
    const r = await call("GET", tpl, { query });
    expectError(r, 401, "unauthorized");
    assert.match(r.headers.get("www-authenticate") || "", /^Bearer\b/i, `${tpl}: WWW-Authenticate: Bearer`);
    expectError(await call("GET", tpl, { query, token: BOGUS_TOKEN }), 401, "unauthorized");
  }
});

test("auth: login rejects bad credentials and bad bodies", async (t) => {
  if (!caps.auth) return t.skip("auth capability is off");
  const wrong = await call("POST", "/api/auth/login", { json: { username: VIEWER.username, password: `${VIEWER.password}-wrong` } });
  expectError(wrong, 401, "invalid_credentials");
  assert.equal(wrong.setCookies.length, 0, "no cookie on a failed login");
  const unknown = await call("POST", "/api/auth/login", { json: { username: "contract-test-no-such-user", password: "x" } });
  expectError(unknown, 401, "invalid_credentials");
  expectError(await call("POST", "/api/auth/login", { json: { username: VIEWER.username } }), 400, "bad_request");
  expectError(await call("POST", "/api/auth/login", { raw: "{not json" }), 400, "bad_request");
});

test("auth: login, refresh rotation, logout; refresh token only in an HttpOnly Secure SameSite=Strict cookie", async (t) => {
  if (!caps.auth) return t.skip("auth capability is off");
  const r = await login(VIEWER);
  assert.match(r.headers.get("cache-control") || "", /no-store/, "login response is Cache-Control: no-store");
  assert.equal(r.json.user.role, "viewer");
  assert.ok(r.json.expires_in <= 900, "access token is short-lived");
  assert.ok(!("refresh_token" in r.json), "no refresh token in the body");
  const c1 = refreshCookie(r);
  assertRefreshCookieFlags(c1);
  assert.ok(!r.text.includes(c1.value), "refresh token value does not appear in the body");
  assert.equal((await call("GET", "/api/equipment", { token: r.json.access_token })).status, 200);

  expectError(await call("POST", "/api/auth/refresh"), 401, "unauthorized");
  const r2 = await call("POST", "/api/auth/refresh", { cookie: `ofdd_refresh=${c1.value}` });
  assert.equal(r2.status, 200, r2.text);
  assert.match(r2.headers.get("cache-control") || "", /no-store/);
  const c2 = refreshCookie(r2);
  assertRefreshCookieFlags(c2);
  assert.notEqual(c2.value, c1.value, "refresh token rotates");
  assert.notEqual(r2.json.access_token, r.json.access_token, "new access token");
  assert.equal(r2.json.user.username, VIEWER.username);
  assert.equal((await call("GET", "/api/equipment", { token: r2.json.access_token })).status, 200);
  expectError(await call("POST", "/api/auth/refresh", { cookie: `ofdd_refresh=${c1.value}` }), 401, "unauthorized");

  const out = await call("POST", "/api/auth/logout", { cookie: `ofdd_refresh=${c2.value}` });
  assert.equal(out.status, 204);
  const cleared = refreshCookie(out);
  assert.ok(cleared.attrs["max-age"] === "0" || (cleared.attrs.expires && Date.parse(cleared.attrs.expires) < Date.now()), "logout clears the cookie");
  expectError(await call("POST", "/api/auth/refresh", { cookie: `ofdd_refresh=${c2.value}` }), 401, "unauthorized");
  assert.equal((await call("POST", "/api/auth/logout")).status, 204, "logout is idempotent");
});

// ---- model ----------------------------------------------------------------------------------------------------
test("equipment: valid tree (parent ids exist), stable pagination", async () => {
  const items = await all("/api/equipment", { token: viewerToken });
  const ids = new Set(items.map((e) => e.id));
  assert.equal(ids.size, items.length, "equipment ids are unique");
  for (const e of items) if (e.parent_id !== null) assert.ok(ids.has(e.parent_id), `${e.id}: parent ${e.parent_id} exists`);
  const paged = await all("/api/equipment", { token: viewerToken }, 1);
  assert.deepEqual(paged.map((e) => e.id), items.map((e) => e.id), "limit=1 pages give the same list");
});

test("points: SI unit, 223P input names, freshness, equipment filter", async () => {
  assert.ok(points.length > 0, "the host lists at least one point");
  const equipment = new Set((await all("/api/equipment", { token: viewerToken })).map((e) => e.id));
  for (const p of points) {
    assert.ok(equipment.has(p.equipment_id), `${p.id}: equipment ${p.equipment_id} exists`);
    if (p.value_type === "boolean") assert.equal(p.unit, "", `${p.id}: boolean points are dimensionless`);
    if (p.last_sample_time === null) assert.equal(p.last_value, null, `${p.id}: no value without a sample`);
  }
  const eq = points[0].equipment_id;
  const filtered = await all("/api/points", { token: viewerToken, query: { equipment: eq } });
  assert.ok(filtered.length > 0 && filtered.every((p) => p.equipment_id === eq), "equipment filter");
  const paged = await all("/api/points", { token: viewerToken }, 3);
  assert.deepEqual(paged.map((p) => p.id), points.map((p) => p.id), "limit=3 pages give the same list");
});

test("pagination: bad limit or cursor is 400", async () => {
  for (const query of [{ limit: 0 }, { limit: -1 }, { limit: "abc" }, { cursor: "contract-test-bad-cursor" }]) {
    expectError(await call("GET", "/api/equipment", { token: viewerToken, query }), 400);
  }
});

// ---- samples --------------------------------------------------------------------------------------------------
test("samples: SI unit of the point, ascending, inside [from, to), last sample = freshness", async () => {
  const p = points.find((x) => x.last_sample_time !== null);
  assert.ok(p, "at least one point has samples");
  const last = Date.parse(p.last_sample_time);
  const from = iso(last - 6 * 3_600_000);
  const to = iso(last + 1000);
  const items = await all("/api/samples", { token: viewerToken, query: { point: p.id, from, to } });
  const r = await call("GET", "/api/samples", { token: viewerToken, query: { point: p.id, from, to, limit: 1 } });
  assert.equal(r.json.point_id, p.id);
  assert.equal(r.json.unit, p.unit, "samples carry the point's SI unit");
  assert.ok(items.length > 0, "samples in the last 6 h before the freshness time");
  let prev = -Infinity;
  for (const s of items) {
    const t = Date.parse(s.t);
    assert.ok(t > prev, "strictly ascending time");
    assert.ok(t >= Date.parse(from) && t < Date.parse(to), "inside [from, to)");
    if (p.value_type === "boolean") assert.ok(s.v === 0 || s.v === 1, "boolean samples are 0/1");
    prev = t;
  }
  assert.equal(items.at(-1).t.replace(/\.000Z$/, "Z"), p.last_sample_time.replace(/\.000Z$/, "Z"), "last sample time equals the point's freshness");
  // `to` is exclusive.
  const excl = await all("/api/samples", { token: viewerToken, query: { point: p.id, from, to: p.last_sample_time } });
  assert.ok(excl.every((s) => Date.parse(s.t) < last), "a sample at `to` is excluded");
  // Offsets are accepted and mean the same instant.
  const off = await call("GET", "/api/samples", { token: viewerToken, query: { point: p.id, from: from.replace("Z", "+00:00"), to: to.replace("Z", "+00:00"), limit: 1 } });
  assert.equal(off.status, 200, off.text);
});

test("samples: 400 for a missing point or bad range, 404 for an unknown point", async () => {
  const id = points[0].id;
  expectError(await call("GET", "/api/samples", { token: viewerToken, query: win }), 400, "bad_request");
  expectError(await call("GET", "/api/samples", { token: viewerToken, query: { point: id, from: win.from } }), 400, "bad_request");
  expectError(await call("GET", "/api/samples", { token: viewerToken, query: { point: id, from: "yesterday", to: win.to } }), 400, "bad_request");
  expectError(await call("GET", "/api/samples", { token: viewerToken, query: { point: id, from: win.to, to: win.from } }), 400, "bad_request");
  expectError(await call("GET", "/api/samples", { token: viewerToken, query: { point: "contract-test-no-such-point", ...win } }), 404, "not_found");
});

// ---- rules and results ----------------------------------------------------------------------------------------
test("rules: inputs by 223P name with SI units; confirm_min null exactly when not tunable", async () => {
  const rules = await all("/api/rules", { token: viewerToken });
  assert.ok(rules.length > 0, "the host lists at least one rule");
  for (const r of rules) {
    assert.equal(r.confirm_min === null, r.confirm_min_default === null, `${r.rule_id}: confirm_min and its default are both null or both set`);
    const names = r.inputs.map((x) => x.name);
    assert.equal(new Set(names).size, names.length, `${r.rule_id}: input names unique`);
  }
});

test("results: status semantics, hours and fault_pct consistent, window overlaps [from, to)", async () => {
  const rows = await all("/api/results", { token: viewerToken, query: win });
  const from = Date.parse(win.from);
  const to = Date.parse(win.to);
  const seen = new Set();
  for (const r of rows) {
    const id = `${r.equipment_id} ${r.rule_id} ${r.window_start}`;
    seen.add(r.status);
    assert.ok(Date.parse(r.window_end) > Date.parse(r.window_start), `${id}: window_end > window_start`);
    assert.ok(Date.parse(r.window_start) < to && Date.parse(r.window_end) > from, `${id}: overlaps the range`);
    if (r.status === "PASS" || r.status === "FAULT") {
      assert.equal(typeof r.fault_hours, "number", `${id}: fault_hours`);
      assert.equal(typeof r.covered_hours, "number", `${id}: covered_hours`);
      assert.equal(typeof r.fault_pct, "number", `${id}: fault_pct`);
      assert.ok(r.status === "FAULT" ? r.fault_hours > 0 : r.fault_hours === 0, `${id}: fault_hours agrees with ${r.status}`);
      assert.ok(r.fault_hours <= r.covered_hours + 1e-9, `${id}: fault_hours <= covered_hours`);
      if (r.active_hours !== null) assert.ok(r.active_hours <= r.covered_hours + 1e-9, `${id}: active_hours <= covered_hours`);
      const denom = r.active_hours ?? r.covered_hours;
      if (denom > 0) assert.ok(Math.abs(r.fault_pct - (100 * r.fault_hours) / denom) < 0.01, `${id}: fault_pct = 100 * fault / ${r.active_hours === null ? "covered" : "active"}`);
    } else {
      for (const k of ["fault_hours", "fault_pct"]) assert.equal(r[k], null, `${id}: ${k} is null for ${r.status}`);
    }
    if (r.status === "NOT_ASSESSED" || r.status === "ERROR") assert.ok(r.reason, `${id}: ${r.status} needs a reason`);
    if (r.status === "METRIC") assert.ok(Object.keys(r.metrics).length > 0, `${id}: METRIC carries metrics`);
  }
  console.log(`# results: ${rows.length} rows, statuses ${[...seen].sort().join(", ") || "none"}`);
  if (rows.length) {
    const one = rows[0];
    const f = await all("/api/results", { token: viewerToken, query: { ...win, equipment: one.equipment_id, rule: one.rule_id } });
    assert.ok(f.length > 0 && f.every((r) => r.equipment_id === one.equipment_id && r.rule_id === one.rule_id), "equipment and rule filters");
  }
  expectError(await call("GET", "/api/results", { token: viewerToken, query: { to: win.to } }), 400, "bad_request");
});

// ---- writes ---------------------------------------------------------------------------------------------------
test("PUT confirm_min: authentication, capability gate, role, validation, round trip", async () => {
  const rules = await all("/api/rules", { token: viewerToken });
  const tunable = rules.find((r) => r.confirm_min !== null);
  const fixed = rules.find((r) => r.confirm_min === null);
  const put = (rule_id, json, token) => call("PUT", "/api/rules/{rule_id}/confirm_min", { params: { rule_id }, json, token });
  const target = tunable || rules[0];
  const writer = caps.auth ? operatorToken : undefined;

  if (caps.auth) expectError(await put(target.rule_id, { confirm_min: 15 }), 401, "unauthorized");
  if (!caps.rules_write) {
    expectError(await put(target.rule_id, { confirm_min: 15 }, writer), 403, "capability_disabled");
    if (caps.auth) expectError(await put(target.rule_id, { confirm_min: 15 }, viewerToken), 403, "capability_disabled");
    const after = (await all("/api/rules", { token: viewerToken })).find((r) => r.rule_id === target.rule_id);
    assert.equal(after.confirm_min, target.confirm_min, "nothing changed");
    return;
  }
  if (caps.auth) expectError(await put(target.rule_id, { confirm_min: 15 }, viewerToken), 403, "forbidden");
  expectError(await put("contract-test-no-such-rule", { confirm_min: 15 }, writer), 404, "not_found");
  if (fixed) expectError(await put(fixed.rule_id, { confirm_min: 15 }, writer), 409, "not_tunable");
  assert.ok(tunable, "with rules_write on, at least one rule is tunable");
  for (const bad of [{ confirm_min: -1 }, { confirm_min: 1441 }, { confirm_min: 1.5 }, { confirm_min: "20" }, {}, { confirm_min: 20, other: 1 }]) {
    expectError(await put(tunable.rule_id, bad, writer), 400, "bad_request");
  }
  const orig = tunable.confirm_min;
  const next = orig === 20 ? 21 : 20;
  try {
    const r = await put(tunable.rule_id, { confirm_min: next }, writer);
    assert.equal(r.status, 200, r.text);
    assert.equal(r.json.rule_id, tunable.rule_id);
    assert.equal(r.json.confirm_min, next);
    const after = (await all("/api/rules", { token: viewerToken })).find((x) => x.rule_id === tunable.rule_id);
    assert.equal(after.confirm_min, next, "GET /api/rules shows the new value");
  } finally {
    const back = await put(tunable.rule_id, { confirm_min: orig }, writer);
    assert.equal(back.status, 200, `restore confirm_min: ${back.text}`);
  }
});

test("spec: every operation is reachable by this suite", () => {
  const covered = new Set(["GET /api/meta", "GET /api/equipment", "GET /api/points", "GET /api/samples", "GET /api/results",
    "GET /api/rules", "PUT /api/rules/{rule_id}/confirm_min", "POST /api/auth/login", "POST /api/auth/refresh", "POST /api/auth/logout"]);
  const ops = Object.entries(spec.paths).flatMap(([p, item]) => Object.keys(item).map((m) => `${m.toUpperCase()} ${p}`));
  assert.deepEqual(ops.filter((o) => !covered.has(o)), [], "operations without a contract test");
});

test("spec: every component schema compiles and its example validates", () => {
  for (const [name, schema] of Object.entries(spec.components.schemas)) {
    const v = ajv.compile({ $ref: `${SCHEMA_ID}#/$defs/${name}` });
    if (schema.example !== undefined) assertValid(v, schema.example, `example of ${name}`);
  }
});
