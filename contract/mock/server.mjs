#!/usr/bin/env node
// Reference mock backend for the Open-FDD UI API (openapi/open-fdd-ui-api.yaml). Node stdlib only.
//
//   node contract/mock/server.mjs [--port 8790] [--host 127.0.0.1] [--writes] [--no-auth]
//
// Synthetic fixture data (fixtures.mjs), in memory. Rule writes are off unless --writes (or OFDD_MOCK_WRITES=1).
// Auth is on unless --no-auth: scrypt-hashed fixture users, short-lived bearer tokens, a rotating refresh token in
// an HttpOnly Secure SameSite=Strict cookie. Not a production server: state is lost on exit.
import http from "node:http";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { EQUIPMENT, POINTS, RULES, RESULTS, USERS } from "./fixtures.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONTRACT_VERSION = /\n {2}version:\s*([0-9]+\.[0-9]+\.[0-9]+)/.exec(
  fs.readFileSync(path.join(HERE, "..", "..", "openapi", "open-fdd-ui-api.yaml"), "utf8"))[1];
const APP_VERSION = fs.readFileSync(path.join(HERE, "..", "..", "VERSION"), "utf8").trim();

const ACCESS_TTL_S = 300;
const REFRESH_TTL_S = 8 * 3600;
const COOKIE = "ofdd_refresh";
const BODY_LIMIT = 16 * 1024;
const MAX_RANGE_MS = 31 * 86_400_000;
const LIMITS = { default: 500, samples: 2000, max: 10000 };

function parseArgs(argv) {
  const o = { port: 8790, host: "127.0.0.1", writes: process.env.OFDD_MOCK_WRITES === "1", auth: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--port") o.port = Number(argv[++i]);
    else if (a === "--host") o.host = argv[++i];
    else if (a === "--writes") o.writes = true;
    else if (a === "--no-auth") o.auth = false;
    else throw new Error(`unknown argument: ${a}`);
  }
  return o;
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const iso = (ms) => new Date(ms).toISOString().replace(/\.000Z$/, "Z");

class ApiError extends Error {
  constructor(status, code, message, details) { super(message); this.status = status; this.code = code; this.details = details; }
}

/** Build a request handler over fresh in-memory state. */
export function createApp({ writes = false, auth = true } = {}) {
  const rules = RULES.map((r) => ({ ...r, inputs: r.inputs.map((x) => ({ ...x })) })).sort((a, b) => cmp(a.rule_id, b.rule_id));
  const equipment = [...EQUIPMENT].sort((a, b) => cmp(a.id, b.id));
  const points = [...POINTS].sort((a, b) => cmp(a.id, b.id));
  const results = [...RESULTS].sort((a, b) => a.window_start - b.window_start || cmp(a.equipment_id, b.equipment_id) || cmp(a.rule_id, b.rule_id));
  const access = new Map();   // token -> {user, exp}
  const refresh = new Map();  // sha256(token) -> {user, exp, family}
  const rotated = new Map();  // sha256(rotated-out token) -> family, to detect reuse

  const sha = (s) => crypto.createHash("sha256").update(s).digest("hex");
  const token = () => crypto.randomBytes(32).toString("base64url");

  function verifyPassword(user, password) {
    const [, n, r, p, salt, hash] = user.hash.split("$");
    const want = Buffer.from(hash, "base64url");
    const got = crypto.scryptSync(password, Buffer.from(salt, "base64url"), want.length, { N: Number(n), r: Number(r), p: Number(p) });
    return crypto.timingSafeEqual(want, got);
  }

  function issue(res, user, family = crypto.randomUUID()) {
    const now = Date.now();
    const at = token();
    const rt = token();
    access.set(at, { user, exp: now + ACCESS_TTL_S * 1000 });
    refresh.set(sha(rt), { user, exp: now + REFRESH_TTL_S * 1000, family });
    res.setHeader("Set-Cookie", `${COOKIE}=${rt}; Path=/api/auth; HttpOnly; Secure; SameSite=Strict; Max-Age=${REFRESH_TTL_S}`);
    return { access_token: at, token_type: "Bearer", expires_in: ACCESS_TTL_S, user: { username: user.username, role: user.role } };
  }

  function cookieToken(req) {
    for (const part of String(req.headers.cookie || "").split(";")) {
      const [k, ...v] = part.trim().split("=");
      if (k === COOKIE) return v.join("=");
    }
    return null;
  }

  /** The caller, or null when auth is off. Throws 401. */
  function caller(req) {
    if (!auth) return null;
    const m = /^Bearer ([A-Za-z0-9_-]+)$/.exec(String(req.headers.authorization || ""));
    const s = m && access.get(m[1]);
    if (!s || s.exp <= Date.now()) {
      if (s) access.delete(m[1]);
      throw new ApiError(401, "unauthorized", m ? "invalid or expired access token" : "missing bearer token");
    }
    return s.user;
  }

  function page(items, q, kind = "default") {
    let limit = kind === "samples" ? LIMITS.samples : LIMITS.default;
    if (q.has("limit")) {
      const raw = q.get("limit");
      limit = /^[0-9]+$/.test(raw) ? Number(raw) : NaN;
      if (!(limit >= 1 && limit <= LIMITS.max)) throw new ApiError(400, "bad_request", `limit must be an integer 1-${LIMITS.max}`, { parameter: "limit" });
    }
    let offset = 0;
    if (q.has("cursor")) {
      const m = /^o([0-9]+)$/.exec(Buffer.from(q.get("cursor"), "base64url").toString());
      if (!m || Number(m[1]) > items.length) throw new ApiError(400, "bad_request", "invalid cursor", { parameter: "cursor" });
      offset = Number(m[1]);
    }
    const next = offset + limit < items.length ? Buffer.from(`o${offset + limit}`).toString("base64url") : null;
    return { items: items.slice(offset, offset + limit), next_cursor: next };
  }

  function range(q) {
    const re = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
    const out = {};
    for (const k of ["from", "to"]) {
      const raw = q.get(k);
      if (!raw) throw new ApiError(400, "bad_request", `${k} is required`, { parameter: k });
      const ms = re.test(raw) ? Date.parse(raw) : NaN;
      if (!Number.isFinite(ms)) throw new ApiError(400, "bad_request", `${k} must be an RFC 3339 date-time`, { parameter: k });
      out[k] = ms;
    }
    if (out.to <= out.from) throw new ApiError(400, "bad_request", "to must be after from", { parameter: "to" });
    if (out.to - out.from > MAX_RANGE_MS) throw new ApiError(400, "range_too_large", "range is longer than 31 days", { parameter: "to" });
    return out;
  }

  async function body(req) {
    if (!/^application\/json\b/i.test(String(req.headers["content-type"] || ""))) {
      throw new ApiError(400, "bad_request", "Content-Type must be application/json");
    }
    const chunks = [];
    let size = 0;
    for await (const c of req) {
      size += c.length;
      if (size > BODY_LIMIT) throw new ApiError(413, "payload_too_large", `body is larger than ${BODY_LIMIT} bytes`);
      chunks.push(c);
    }
    try {
      const v = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("not an object");
      return v;
    } catch {
      throw new ApiError(400, "bad_request", "body must be a JSON object");
    }
  }

  const pointOut = ({ series, last_sample_time, ...p }) => ({ ...p, last_sample_time: last_sample_time == null ? null : iso(last_sample_time) });
  const resultOut = (r) => ({ ...r, window_start: iso(r.window_start), window_end: iso(r.window_end) });

  const routes = {
    "GET /api/meta": () => [200, {
      contract_version: CONTRACT_VERSION,
      app: { name: "open-fdd-contract-mock", version: APP_VERSION },
      capabilities: { rules_write: writes, export_csv: false, export_parquet: false, sparql: false, auth },
    }],
    "GET /api/equipment": (req, q) => { caller(req); return [200, page(equipment, q)]; },
    "GET /api/points": (req, q) => {
      caller(req);
      const eq = q.get("equipment");
      return [200, page(points.filter((p) => !eq || p.equipment_id === eq).map(pointOut), q)];
    },
    "GET /api/samples": (req, q) => {
      caller(req);
      const id = q.get("point");
      if (!id) throw new ApiError(400, "bad_request", "point is required", { parameter: "point" });
      const { from, to } = range(q);
      const p = points.find((x) => x.id === id);
      if (!p) throw new ApiError(404, "not_found", "unknown point", { parameter: "point" });
      const items = p.series.filter((s) => s.t >= from && s.t < to).map((s) => ({ t: iso(s.t), v: s.v }));
      return [200, { point_id: p.id, unit: p.unit, ...page(items, q, "samples") }];
    },
    "GET /api/results": (req, q) => {
      caller(req);
      const { from, to } = range(q);
      const eq = q.get("equipment");
      const rule = q.get("rule");
      const rows = results.filter((r) => r.window_start < to && r.window_end > from && (!eq || r.equipment_id === eq) && (!rule || r.rule_id === rule));
      return [200, page(rows.map(resultOut), q)];
    },
    "GET /api/rules": (req, q) => { caller(req); return [200, page(rules, q)]; },
    "POST /api/auth/login": async (req, _q, res) => {
      const b = await body(req);
      if (typeof b.username !== "string" || typeof b.password !== "string" || !b.username || !b.password
        || b.username.length > 128 || b.password.length > 1024) {
        throw new ApiError(400, "bad_request", "username and password are required strings");
      }
      const user = USERS.find((u) => u.username === b.username);
      // Hash even for an unknown user, so timing does not reveal which usernames exist.
      const ok = verifyPassword(user || USERS[0], b.password) && !!user;
      if (!ok) throw new ApiError(401, "invalid_credentials", "wrong username or password");
      return [200, issue(res, user)];
    },
    "POST /api/auth/refresh": (req, _q, res) => {
      const rt = cookieToken(req);
      const key = rt && sha(rt);
      const s = key && refresh.get(key);
      if (key && !s && rotated.has(key)) {
        // Reuse of a rotated-out token: revoke the whole family (the newest token too).
        const fam = rotated.get(key);
        for (const [k, v] of refresh) if (v.family === fam) refresh.delete(k);
      }
      if (!s || s.exp <= Date.now()) throw new ApiError(401, "unauthorized", "missing, expired or revoked refresh token");
      refresh.delete(key); // rotation: the old refresh token is now rejected
      rotated.set(key, s.family);
      return [200, issue(res, s.user, s.family)];
    },
    "POST /api/auth/logout": (req, _q, res) => {
      const rt = cookieToken(req);
      if (rt) refresh.delete(sha(rt));
      res.setHeader("Set-Cookie", `${COOKIE}=; Path=/api/auth; HttpOnly; Secure; SameSite=Strict; Max-Age=0`);
      return [204, null];
    },
  };

  async function putConfirmMin(req, ruleId) {
    const user = caller(req);
    if (!writes) throw new ApiError(403, "capability_disabled", "rule writes are disabled on this host (capabilities.rules_write is false)");
    if (user && user.role !== "operator" && user.role !== "admin") throw new ApiError(403, "forbidden", "operator or admin role required");
    const rule = rules.find((r) => r.rule_id === ruleId);
    if (!rule) throw new ApiError(404, "not_found", "unknown rule");
    if (rule.confirm_min == null) throw new ApiError(409, "not_tunable", "this rule has no confirmation delay");
    const b = await body(req);
    const v = b.confirm_min;
    if (Object.keys(b).some((k) => k !== "confirm_min") || !Number.isInteger(v) || v < 0 || v > 1440) {
      throw new ApiError(400, "bad_request", "confirm_min must be an integer 0-1440", { field: "confirm_min" });
    }
    rule.confirm_min = v;
    return [200, rule];
  }

  return async function handle(req, res) {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Referrer-Policy", "no-referrer");
    let status;
    let payload;
    try {
      const url = new URL(req.url, "http://mock.invalid");
      const isAuth = url.pathname.startsWith("/api/auth/");
      if (isAuth && !auth) throw new ApiError(404, "not_found", "this host does not authenticate through /api/auth");
      const m = /^\/api\/rules\/([^/]+)\/confirm_min$/.exec(url.pathname);
      const route = routes[`${req.method} ${url.pathname}`];
      if (m && req.method === "PUT") [status, payload] = await putConfirmMin(req, decodeURIComponent(m[1]));
      else if (route) [status, payload] = await route(req, url.searchParams, res);
      else {
        const allow = m ? ["PUT"] : Object.keys(routes).filter((k) => k.endsWith(` ${url.pathname}`)).map((k) => k.split(" ")[0]);
        if (allow.length) {
          res.setHeader("Allow", allow.join(", "));
          throw new ApiError(405, "method_not_allowed", "method not allowed");
        }
        throw new ApiError(404, "not_found", "no such endpoint");
      }
    } catch (e) {
      if (!(e instanceof ApiError)) { console.error(e); e = new ApiError(500, "internal", "internal error"); }
      status = e.status;
      payload = { error: { code: e.code, message: e.message, ...(e.details ? { details: e.details } : {}) } };
      if (status === 401 && !req.url.startsWith("/api/auth/")) {
        res.setHeader("WWW-Authenticate", e.message === "missing bearer token" ? 'Bearer realm="open-fdd"' : 'Bearer realm="open-fdd", error="invalid_token"');
      }
    }
    if (payload == null) { res.writeHead(status); res.end(); return; }
    const text = JSON.stringify(payload);
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(text) });
    res.end(text);
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const opts = parseArgs(process.argv.slice(2));
  const server = http.createServer(createApp(opts));
  server.listen(opts.port, opts.host, () => {
    const { port } = /** @type {import("node:net").AddressInfo} */ (server.address());
    console.log(`open-fdd contract mock on http://${opts.host}:${port} (contract ${CONTRACT_VERSION}, auth ${opts.auth ? "on" : "off"}, writes ${opts.writes ? "on" : "off"})`);
  });
}
