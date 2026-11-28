"use strict";
/**
 * Which runtime build this install is. `static/engine-build.json` is the source copy (the DuckDB build).
 * `scripts/nf/build_app_dist.py` rewrites it, and the plugin HTML, for the Timescale recipe.
 * The visible badge is the label only ("DuckDB build" or "Timescale build"). `libraryVersion` is for the
 * status API and is not shown in the badge.
 */
const fs = require("fs");
const path = require("path");

const BUILD_FILE = path.join(__dirname, "..", "..", "static", "engine-build.json");
const LABELS = Object.freeze({ duckdb: "DuckDB build", timescale: "Timescale build" });

function readBuild() {
  try {
    const j = JSON.parse(fs.readFileSync(BUILD_FILE, "utf8"));
    if (j && (j.id === "duckdb" || j.id === "timescale")) return j;
  } catch (e) { /* missing file: the source default is the DuckDB build */ }
  return { id: "duckdb", label: LABELS.duckdb, library: "@duckdb/node-api", libraryVersion: "2.0.1-r.1" };
}

function record() {
  const j = readBuild();
  return {
    id: j.id,
    label: LABELS[j.id],
    library: j.library || (j.id === "timescale" ? "pg" : "@duckdb/node-api"),
    libraryVersion: j.libraryVersion || (j.id === "timescale" ? "8.23.1" : "2.0.1-r.1"),
  };
}

/** The sentence the UI, the log and the status API show. No engine is substituted. */
function duckdbLoadError(reason) {
  const why = String(reason || "module did not load").replace(/\s+/g, " ").trim();
  return `DuckDB engine failed to load: ${why}. Reinstall the DuckDB build or switch to the Timescale build.`;
}

function retiredEngineError(name) {
  return `engine "${name}" was removed in 5.0.22. Set the app option engine to "duckdb" (single site) or "timescale".`;
}

function duckdbLoadable() {
  try {
    require("@duckdb/node-api");
    return { ok: true, reason: "" };
  } catch (e) {
    return { ok: false, reason: (e && e.message) || String(e) };
  }
}

/** `hasDuckdb` is duckdbLoadable, `() => true/false` (older tests), or `() => ({ ok, reason })`. */
function describeLoad(hasDuckdb) {
  const fn = hasDuckdb || duckdbLoadable;
  let probe;
  try { probe = fn(); } catch (e) { return { ok: false, reason: (e && e.message) || String(e) }; }
  if (probe && typeof probe === "object") {
    return { ok: !!probe.ok, reason: probe.reason || (probe.ok ? "" : "module did not load") };
  }
  return probe ? { ok: true, reason: "" } : { ok: false, reason: "module did not load" };
}

/** Status-API fields. On the DuckDB build a package that does not load sets `engine_error` and nothing else runs. */
function statusFields(load) {
  const rec = record();
  let engine_error = null;
  if (rec.id === "duckdb") {
    const probe = describeLoad(load);
    if (!probe.ok) engine_error = duckdbLoadError(probe.reason);
  }
  return {
    engine_build: rec.label,
    engine_library: rec.library,
    engine_library_version: rec.libraryVersion,
    engine_error,
  };
}

module.exports = {
  LABELS, BUILD_FILE, readBuild, record, duckdbLoadError, retiredEngineError, duckdbLoadable, describeLoad, statusFields,
};
