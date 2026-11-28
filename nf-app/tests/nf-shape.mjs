// Shape comparison for the recorded-NF contract tests: same keys, same JSON types (an int64 is a STRING in NF's JSON),
// free-form maps (attrs, args) compared loosely. Returns a list of problems, empty when the shapes match.
const kind = (v) => (v === null ? "null" : Array.isArray(v) ? "array" : typeof v);

/**
 * @param {any} actual what the mock sent
 * @param {any} expected what the real NF sent (a recording)
 * @param {{ free?: string[], optional?: string[], ignore?: string[], keyed?: string[] }} [opts]
 *   free: keys holding a free-form map (only checked to be an object); optional: keys that may be absent;
 *   ignore: keys skipped; keyed: keys holding a map whose values all share one shape (hook-run "results", by group).
 */
export function shapeProblems(actual, expected, opts = {}, at = "$") {
  const free = new Set(opts.free || ["attrs", "args", "stats"]);
  const optional = new Set(opts.optional || []);
  const ignore = new Set(opts.ignore || []);
  const keyed = new Set(opts.keyed || ["results"]);
  const ka = kind(actual), ke = kind(expected);
  if (ka !== ke) return [`${at}: ${ka}, NF sends ${ke}`];
  if (ke === "array") {
    if (!expected.length || !actual.length) return [];
    // An element may be any of the recorded variants (resources: storage or memory; a BACnet value: real, enumerated, ...).
    return actual.flatMap((item, i) => {
      const tries = expected.map((e) => shapeProblems(item, e, opts, `${at}[${i}]`));
      return tries.some((t) => t.length === 0) ? [] : tries.reduce((a, b) => (b.length < a.length ? b : a));
    });
  }
  if (ke !== "object") return [];
  const out = [];
  for (const k of Object.keys(expected)) {
    if (ignore.has(k)) continue;
    if (!(k in actual)) { if (!optional.has(k)) out.push(`${at}.${k}: missing (NF sends it)`); continue; }
    if (free.has(k)) { if (kind(actual[k]) !== "object") out.push(`${at}.${k}: ${kind(actual[k])}, NF sends a map`); continue; }
    if (keyed.has(k) && kind(expected[k]) === "object") {
      const first = Object.values(expected[k])[0];
      for (const [g, v] of Object.entries(actual[k] || {})) if (first !== undefined) out.push(...shapeProblems(v, first, opts, `${at}.${k}[${JSON.stringify(g)}]`));
      continue;
    }
    out.push(...shapeProblems(actual[k], expected[k], opts, `${at}.${k}`));
  }
  for (const k of Object.keys(actual)) if (!(k in expected) && !ignore.has(k) && !optional.has(k)) out.push(`${at}.${k}: NF does not send it`);
  return out;
}
