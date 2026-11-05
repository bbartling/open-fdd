/** In-flight dedup for identical historian/analytics reads (bounded memory). */

const inflight = new Map();
const MAX_KEYS = 64;

export function dedupeAsync(key, factory) {
  const existing = inflight.get(key);
  if (existing) return existing;
  const promise = Promise.resolve()
    .then(factory)
    .finally(() => {
      if (inflight.get(key) === promise) inflight.delete(key);
    });
  inflight.set(key, promise);
  if (inflight.size > MAX_KEYS) {
    const first = inflight.keys().next().value;
    if (first != null && first !== key) inflight.delete(first);
  }
  return promise;
}

export function dedupeKey(parts) {
  return JSON.stringify(parts);
}
