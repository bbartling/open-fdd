// Shared NF access for the Open-FDD pages: same-origin /api/v1/* calls with
// the console's login (LAN auth bypass, or the Clerk token through Normal Online).

// Bearer source for the API, or null when NF needs none (LAN auth bypass).
let getToken = null;

function loadScript(src, attrs = {}) {
  return new Promise((ok, no) => {
    const s = document.createElement("script");
    s.src = src; s.async = true; s.crossOrigin = "anonymous";
    for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, v);
    s.onload = ok; s.onerror = () => no(new Error(`could not load ${src}`));
    document.head.appendChild(s);
  });
}

// Through Normal Online the console signs every API call with a short-lived
// Clerk JWT (template "ConsoleJWT"); cookies alone get a 401. platform/info
// is open and says which identity provider this NF uses, so do the same.
async function initAuth() {
  const r = await fetch("/api/v1/platform/info", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`/api/v1/platform/info → HTTP ${r.status} (sign in to the portal first)`);
  const info = await r.json();
  if (info.provider !== "IAM_NF_CLERK" || !info.clientid) return info;
  const pk = info.clientid;
  const fapi = atob(pk.split("_")[2]).replace(/\$$/, "");
  await loadScript(`https://${fapi}/npm/@clerk/clerk-js@${CLERK_JS_VERSION}/dist/clerk.browser.js`,
    { "data-clerk-publishable-key": pk });
  await window.Clerk.load();
  if (!window.Clerk.session) throw new Error("not signed in to Normal Portal on this host");
  getToken = () => window.Clerk.session.getToken({ template: "ConsoleJWT" });
  return info;
}

// Pinned: the portal sign-in loads clerk-js from the host in the portal's publishable key
// (the only script these pages load from outside their own origin). Bump deliberately.
const CLERK_JS_VERSION = "5.128.1";

// Reads that are safe to repeat. Everything else (StartHook, writes, deletes) is sent once:
// if the response is lost the caller must look, not re-fire (a second StartHook = a second run).
const IDEMPOTENT_POSTS = new Set(["/api/v1/point/query", "/api/v1/auth/token"]);

/** @param {string} path @param {string} method */
function isRetryable(path, method) {
  if (method === "GET") return true;
  return method === "POST" && IDEMPOTENT_POSTS.has(path.split("?")[0]);
}

/**
 * @param {string} path
 * @param {unknown} [body] POSTed as JSON when given
 * @param {{method?: string}} [opts] override the method (PATCH/DELETE); default GET, or POST with a body
 * @returns {Promise<any>}
 */
async function api(path, body, opts = {}) {
  /** @type {Record<string, string>} */
  const headers = body ? { "Content-Type": "application/json" } : {};
  const method = opts.method || (body ? "POST" : "GET");
  const init = body ? { method, body: JSON.stringify(body) } : method === "GET" ? {} : { method };
  const retry = isRetryable(path, method);
  for (let attempt = 1; ; attempt++) {
    if (getToken) headers.Authorization = `Bearer ${await getToken()}`;
    const r = await fetch(path, { credentials: "same-origin", headers, ...init });
    if (r.ok) return r.json();
    // NF occasionally answers a transient empty-body 403; retry reads a few times.
    if (retry && [403, 429, 502, 503, 504].includes(r.status) && attempt < 4) {
      await new Promise((ok) => setTimeout(ok, 500 * 2 ** attempt));
      continue;
    }
    throw new Error(`${path.split("?")[0]} → HTTP ${r.status}`);
  }
}

/**
 * Live point values pushed by NF (PointManager.ObserveDataUpdates, a gRPC server stream
 * that Envoy exposes as one long chunked JSON array at /api/v1/point/updates/data).
 * Calls onValue({ uuid, value }) per update as it arrives; reconnects with backoff.
 * onState(true|false) reports whether the stream is up. Returns a stop() function.
 */
/**
 * @param {string[]} uuids
 * @param {(v: {uuid: string, value: any}) => void} onValue
 * @param {(up: boolean, err?: any) => void} [onState]
 * @returns {() => void}
 */
function streamUpdates(uuids, onValue, onState = () => {}) {
  let stopped = false, ctrl = null, delay = 2000;
  const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const q = uuids.map((u) => "uuids=" + encodeURIComponent(u)).join("&");
  async function run() {
    while (!stopped) {
      let got = 0;  // values received on this connection
      try {
        ctrl = new AbortController();
        const headers = getToken ? { Authorization: `Bearer ${await getToken()}` } : {};
        // wait=true keeps the stream open; without it NF answers `[]` at once and closes.
        const r = await fetch(`/api/v1/point/updates/data?${q}&wait=true`, { credentials: "same-origin", headers, signal: ctrl.signal });
        // NF's Envoy ends a stream that has been quiet ~15 s ("upstream request timeout",
        // 504; the LAN Caddy turns it into 204): normal, so reopen without leaving "live".
        if (r.status === 504 || r.status === 204) { await r.body?.cancel(); await pause(1000); continue; }
        if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
        onState(true);
        delay = 2000;
        // The body is `[{...}\n,{...}\n,...`: cut out each top-level object as it completes.
        const reader = r.body.getReader(), dec = new TextDecoder();
        let buf = "", depth = 0, start = -1, inStr = false, escNext = false, pos = 0;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          for (; pos < buf.length; pos++) {
            const ch = buf[pos];
            if (inStr) { if (escNext) escNext = false; else if (ch === "\\") escNext = true; else if (ch === '"') inStr = false; continue; }
            if (ch === '"') inStr = true;
            else if (ch === "{") { if (depth++ === 0) start = pos; }
            else if (ch === "}" && --depth === 0 && start >= 0) {
              try { onValue(JSON.parse(buf.slice(start, pos + 1))); got++; } catch { /* skip a bad chunk */ }
              buf = buf.slice(pos + 1); pos = -1; start = -1;
            }
          }
        }
        await pause(1000);  // NF closed a stream it had served: reopen (never a tight loop)
      } catch (e) {
        if (stopped) return;
        // NF's Envoy closes a stream right after a batch without the final chunk, so the
        // browser reports a network error. If values came through, that's a normal end.
        if (got) { await pause(1000); continue; }
        onState(false, e);
        await pause(delay);
        delay = Math.min(delay * 2, 60000);
      }
    }
  }
  run();
  return () => { stopped = true; ctrl?.abort(); };
}

/** @param {string} property @param {string} text */
const field = (property, text) => ({ field: { property, text } });

/** @param {object} body point/query body; pages are followed @returns {Promise<any[]>} */
async function queryAll(body) {
  const out = [];
  let pageToken = "";
  do {
    const page = await api("/api/v1/point/query", { pageSize: 500, ...body, ...(pageToken && { pageToken }) });
    out.push(...(page.points || []));
    pageToken = page.nextPageToken || "";
  } while (pageToken);
  return out;
}

/** @param {unknown} s */
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---- BACnet helpers -----------------------------------------------------------
const BAC_UNITS = { 29: "%RH", 53: "Pa", 58: "inH₂O", 62: "°C", 64: "°F", 84: "cfm", 95: "", 96: "ppm", 98: "%" };
const BAC_SHORT = {
  OBJECT_ANALOG_INPUT: "ai", OBJECT_ANALOG_OUTPUT: "ao", OBJECT_ANALOG_VALUE: "av",
  OBJECT_BINARY_INPUT: "bi", OBJECT_BINARY_OUTPUT: "bo", OBJECT_BINARY_VALUE: "bv",
  OBJECT_MULTI_STATE_VALUE: "msv", OBJECT_SCHEDULE: "sched", OBJECT_DEVICE: "d",
};
const scalar = (v = {}) => v.real ?? v.double ?? v.unsigned ?? v.signed ?? v.enumerated ?? v.boolean ?? v.characterString;
const propOf = (obj, prop) => scalar((obj.props || []).find((p) => p.property === prop)?.value);
const objId = (o) => `${BAC_SHORT[o.objectType] || o.objectType}.${o.instance}`;

// BACnet/IP MAC of NF's own port (4 address bytes + 2 port bytes, base64) so a
// read goes out over the BACnet stack like any other client's would.
function selfAddress(ports) {
  const ip = (ports.ports || []).find((p) => p.ip && p.status === "NETWORK_PORT_STATUS_READY");
  if (!ip) return null;
  const host = ip.ip.localIfAddress.split("/")[0];
  const bytes = [...host.split(".").map(Number), ip.ip.port >> 8, ip.ip.port & 255];
  return { mac: btoa(String.fromCharCode(...bytes)), portId: ip.portId, label: `${host}:${ip.ip.port}` };
}

/** @param {any} dev @param {{mac: string, portId: any} | null} addr @param {{objectType: string, instance: any}} objectId @param {string} [property] */
async function readProp(dev, addr, objectId, property = "PROP_PRESENT_VALUE") {
  const q = new URLSearchParams({
    "object_id.object_type": objectId.objectType, "object_id.instance": objectId.instance,
    property_id: property, array_index: "4294967295",
  });
  if (addr) { q.set("device_address.mac", addr.mac); q.set("device_address.port_id", addr.portId); }
  else q.set("device_address.device_id", dev);
  return scalar((await api(`/api/v1/bacnet/readproperty?${q}`)).value);
}
