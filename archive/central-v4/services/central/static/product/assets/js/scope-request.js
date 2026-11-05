/** Immutable scope tickets: generation counter + AbortController (SPA scopedLoad parity). */

export function createScopeHolder() {
  return { generation: 0, controller: null };
}

export function beginScopedRequest(holder) {
  holder.controller?.abort();
  const controller = new AbortController();
  holder.controller = controller;
  const generation = holder.generation + 1;
  holder.generation = generation;
  return {
    generation,
    signal: controller.signal,
    isCurrent: () => holder.generation === generation && !controller.signal.aborted,
  };
}

export function cancelScopedRequest(holder) {
  holder.controller?.abort();
  holder.generation += 1;
  holder.controller = null;
}

export function isAbortError(err) {
  if (!err || typeof err !== "object" || !("name" in err)) return false;
  return String(err.name) === "AbortError";
}

/** @param {{ site: string, equip: string, generation?: number }} raw */
export function freezeScope(raw) {
  return Object.freeze({
    site: String(raw.site ?? "").trim(),
    equip: String(raw.equip ?? "").trim(),
    generation: raw.generation ?? 0,
  });
}

export function scopeKey(scope) {
  return `${scope.site}\0${scope.equip}\0${scope.generation ?? 0}`;
}

export function scopesEqual(a, b) {
  return a.site === b.site && a.equip === b.equip && (a.generation ?? 0) === (b.generation ?? 0);
}
