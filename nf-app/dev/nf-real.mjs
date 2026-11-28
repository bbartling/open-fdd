// What a real Normal Framework 3.10.11 does, as recorded from a live instance (nf-app/tests/fixtures/nf-real/*.json).
// The dev mock (mock-nf.mjs) uses these helpers so its answers have the real shapes, status codes and quirks.
// Contract tests (nf-app/tests/nf-real-contract.test.mjs) replay the recordings against the mock.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FIXTURE_DIR = path.join(HERE, "..", "tests", "fixtures", "nf-real");

/** The recorded response body of fixture `id` (a fresh copy every call). */
export function recorded(id) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, `${id}.json`), "utf8")).response.body;
}

const LAYERS = recorded("layers__list").layers;
/** Every layer name NF knows. A query on any other name is a 400. */
export const LAYER_NAMES = new Set(LAYERS.map((l) => l.name));
/** Layers a write can land in. "default" is a UNION layer: a write to it, to an unknown name, or to no layer at all is
 *  accepted ("success": true) but applies nothing. Only an explicit base layer such as "model" or "automation" is applied. */
export const BASE_LAYERS = new Set(LAYERS.filter((l) => l.kind === "LAYER_BASE").map((l) => l.name));

// ---- errors NF's gateway sends ---------------------------------------------------------------------
// Console API errors are an EMPTY body: gRPC-style failures carry content-type application/grpc, JSON decode
// failures text/plain. A client that does r.json() on them throws. Routes NF does not have answer with the web
// console (index.html, 200) for a GET and a 405 text/html for anything else.
export function emptyError(res, status, contentType = "application/grpc") {
  res.writeHead(status, { "Content-Type": contentType });
  res.end();
}
export const grpcError = (res, status) => emptyError(res, status, "application/grpc");
export const textError = (res, status) => emptyError(res, status, "text/plain");
const SPA = "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\" /><title>Normal Framework</title></head><body><div id=\"root\"></div></body></html>\n";
export function unknownRoute(res, method) {
  if (method === "GET") { res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); return res.end(SPA); }
  res.writeHead(405, { "Content-Type": "text/html; charset=utf-8" });
  return res.end("");
}

// ---- points -----------------------------------------------------------------------------------------
/** A point/query record the way NF returns it: every field present, enums as names, the REQUESTED layer name. */
export function realPoint(record, layer) {
  const hasValue = !!record.latestValue;
  const out = {
    uuid: record.uuid, name: record.name, layer, version: "",
    attrs: record.attrs || {},
    ...(record.hpldata ? { hpldata: record.hpldata } : {}),
    ...(hasValue ? { latestValue: record.latestValue } : {}),
    displayUnits: record.displayUnits || "", parentUuid: record.parentUuid || "", protocolId: record.protocolId || "",
    pointType: record.pointType || "POINT", splitAttrs: record.splitAttrs || [],
    description: record.description || "", parentName: record.parentName || "",
    units: record.units || "UNITS_UNKNOWN", hplDriver: record.hplDriver || "", conversionId: record.conversionId || "",
    qualityFlags: record.qualityFlags || (hasValue ? [] : ["QUALITY_FLAG_NEVER_REPORTED"]),
    writability: record.writability || "WRITABILITY_UNKNOWN",
  };
  return out;
}

/** UpdatePoints answer: one result per record, "newVersion" empty, a queue task id (updates are applied asynchronously). */
export function updateResult(record, n) {
  return { uuid: record.uuid, success: true, newVersion: "", taskUuid: `points_updates_queue:mock-${n}` };
}

// ---- history (GET /api/v1/point/data) ----------------------------------------------------------------
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** `window` is a protobuf duration: "300s". A bare "300" or "5m" is a 400. Returns seconds, or null. */
export function parseWindow(text) {
  const m = /^(\d+(?:\.\d+)?)s$/.exec(String(text));
  return m ? Number(m[1]) : null;
}
export const AGG_METHODS = new Set(["AVERAGE", "MIN", "MAX", "SUM", "FIRST", "LAST", "COUNT"]);
/** Raw samples: nine fractional digits, and NF puts the sample's MILLISECONDS in the low three (…:08.000000207Z for 08.207). */
export function rawTs(ms) {
  const iso = new Date(ms).toISOString();
  return `${iso.slice(0, 19)}.000000${iso.slice(20, 23)}Z`;
}
/** Resampled buckets: whole seconds, no fraction (…:35:00Z). */
export const bucketTs = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

// ---- hooks -------------------------------------------------------------------------------------------
/** A hook run as NF lists it. int64 fields are strings ("pid", "invocationCount"), "results" is keyed by group ("")
 *  and empty unless include_results=true, events are newest first. A hook that answers ok:false is still STATE_SUCCESS. */
export function makeRun(pid, args, events, now = Date.now()) {
  const t = (ms) => `${new Date(ms).toISOString().slice(0, 23)}000000Z`;     // nine fractional digits, like NF
  const start = now - 1000;
  return {
    hookId: "", pid: String(pid), state: "STATE_SUCCESS", message: "", trigger: "TRIGGER_REQUEST",
    startTime: t(start), endTime: t(now), args: args || {},
    results: { "": { endTime: t(now), state: "STATE_SUCCESS", invocationCount: "0", returnValue: "",
      events: events.map((message) => ({ ts: new Date(now).toISOString(), message })),
      startTime: t(start), enqueuedTime: t(start - 2), group: "", pid: String(pid), taskUuid: "", args: {}, runtimePid: 1000 } },
    version: "", enqueuedTime: t(start - 2), stats: { 6: "1" },
  };
}
/** Hook ids an installed Open-FDD app really has (from the manifests). Invoking any other id is a 404. */
export function manifestHookIds(root) {
  const ids = new Set();
  for (const rel of ["nf-app/app.json", "lite/app.json"]) {
    try {
      const m = JSON.parse(fs.readFileSync(path.join(root, rel), "utf8"));
      for (const h of m.hooks || []) ids.add(typeof h === "string" ? h : h.id);
    } catch { /* manifest absent: nothing to add */ }
  }
  return ids;
}

// ---- platform ------------------------------------------------------------------------------------------
export function platformInfo({ real, version, timezone }) {
  const info = recorded("platform__info");
  if (!real) {
    info.version = version;
    delete info.timezone;
    for (const r of info.resources) if (r.memory) r.memory.totalBytes = String(4 * 1024 ** 3);
  }
  if (timezone) info.timezone = timezone;
  return info;
}
