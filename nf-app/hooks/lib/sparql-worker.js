'use strict';
// SPARQL evaluation in a worker thread (FULL edition, sparql-data hook). Oxigraph evaluates synchronously and cannot
// be interrupted from the thread that runs it; in a worker the hook can stop a runaway query by terminating the
// worker (same idea as the browser panel's Worker). Message in: {turtle, query, cap, maxTriples}; out:
// {ok: true, r: <sparqlExec answer>} | {ok: false, error}. Read-only: the store lives only inside this worker.
const { parentPort, workerData } = require('worker_threads');

function oxigraph() {
  try { return require(/** @type {string} */ ('oxigraph')); }
  catch (e) { throw new Error(`oxigraph is not installed (${e && e.message}). Install the app dependencies.`); }
}

function splitPrologue(query) {
  let rest = String(query), prologue = '';
  for (;;) {
    const m = /^(?:\s+|#[^\r\n]*(?:\r?\n|$)|PREFIX\s+[^\s:]*:\s*<[^>]*>|BASE\s*<[^>]*>)/i.exec(rest);
    if (!m) break;
    prologue += m[0]; rest = rest.slice(m[0].length);
  }
  return { prologue, body: rest };
}

function evaluate({ turtle, query, cap, maxTriples }) {
  const lib = require('../../static/sparql.js');
  const store = lib.sparqlLoadStore(oxigraph(), turtle, maxTriples);
  // Bound the SELECT inside the engine as well as the returned JSON. PREFIX/BASE belong outside a subquery.
  const parts = splitPrologue(query);
  const form = lib.sparqlCheckQuery(query).form;
  const bounded = form === 'SELECT' ? parts.prologue + '\nSELECT * WHERE { {\n' + parts.body + '\n} } LIMIT ' + (cap + 1) : query;
  const r = lib.sparqlExec(store, bounded, cap);
  if (r && r.kind === 'graph') delete r.triples;
  return r;
}

if (parentPort && workerData && workerData.ofddSparqlWorker) {
  parentPort.on('message', (msg) => {
    try {
      parentPort.postMessage({ ok: true, r: evaluate(msg) });
    } catch (e) {
      parentPort.postMessage({ ok: false, error: String((e && e.message) || e) });
    }
  });
}

module.exports = { evaluate };