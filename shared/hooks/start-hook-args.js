// Normal Framework StartHook arguments arrive as a string-to-string map.
// Keep this helper small and schema-driven so ordinary string fields remain strings.

/** Parse a JSON-encoded top-level argument object, preserving an already typed object. */
function objectArgs(args) {
  const parsed = typeof args === 'string' ? JSON.parse(args) : args;
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? { ...parsed } : {};
}

/**
 * Coerce only declared structured fields from NF's string-to-string StartHook map.
 * Invalid JSON and non-numeric values are left unchanged for the hook's normal validator.
 * @param {any} args
 * @param {{jsonFields?: string[], numberFields?: string[], booleanFields?: string[], expandWindowHours?: boolean}} [fields]
 */
function normalizeStartHookArgs(args, fields = {}) {
  const out = objectArgs(args);
  for (const key of fields.jsonFields || []) {
    if (typeof out[key] !== 'string') continue;
    try { out[key] = JSON.parse(out[key]); } catch (_) { /* preserve for field validation */ }
  }
  for (const key of fields.numberFields || []) {
    if (typeof out[key] !== 'string' || out[key].trim() === '') continue;
    const n = Number(out[key]);
    if (Number.isFinite(n)) out[key] = n;
  }
  for (const key of fields.booleanFields || []) {
    if (out[key] === 'true') out[key] = true;
    else if (out[key] === 'false') out[key] = false;
  }
  if (fields.expandWindowHours && (out.from == null || out.from === '') && (out.to == null || out.to === '')) {
    const hours = Number(out.windowHours);
    if (Number.isFinite(hours) && hours > 0) {
      const to = new Date();
      const from = new Date(to.getTime() - hours * 3600 * 1000);
      if (Number.isFinite(from.getTime())) {
        out.to = to.toISOString();
        out.from = from.toISOString();
      }
    }
  }
  return out;
}

/**
 * Read StartHook arguments from NF's supported context locations, then normalize declared fields.
 * config fallback is retained for hooks that historically accepted args there.
 * @param {any} ctx
 * @param {{configFallback?: boolean, jsonFields?: string[], numberFields?: string[], booleanFields?: string[], expandWindowHours?: boolean}} [fields]
 */
function startHookArgs(ctx, fields = {}) {
  const raw = (ctx && (ctx.args || ctx.params || (ctx.sdk && ctx.sdk.args) ||
    (fields.configFallback && ctx.config))) || {};
  return normalizeStartHookArgs(raw, fields);
}

module.exports = { normalizeStartHookArgs, startHookArgs };
