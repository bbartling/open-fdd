import { useEffect, useRef, useState } from "react";

export type ScopeHolder = {
  generation: number;
  controller: AbortController | null;
};

export type ScopedTicket = {
  generation: number;
  signal: AbortSignal;
  isCurrent: () => boolean;
};

export function createScopeHolder(): ScopeHolder {
  return { generation: 0, controller: null };
}

/** Abort the previous request and return a ticket only the newest call may commit. */
export function beginScopedRequest(holder: ScopeHolder): ScopedTicket {
  holder.controller?.abort();
  const controller = new AbortController();
  holder.controller = controller;
  const generation = holder.generation + 1;
  holder.generation = generation;
  return {
    generation,
    signal: controller.signal,
    isCurrent: () =>
      holder.generation === generation && !controller.signal.aborted,
  };
}

export function cancelScopedRequest(holder: ScopeHolder): void {
  holder.controller?.abort();
  holder.generation += 1;
  holder.controller = null;
}

export function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== "object" || !("name" in err)) return false;
  return String((err as { name: unknown }).name) === "AbortError";
}

export type ScopedLoad<T> = {
  value: T;
  /** Scope key whose value is in `value`. Empty until that load commits. */
  committedKey: string;
  error: string | null;
  loading: boolean;
};

/**
 * Load data for one scope key. Changing the key aborts the previous request
 * and ignores its result, so a late response cannot paint the new scope.
 * The loader is read from a ref: a new function identity does not refetch.
 */
export function useScopedLoad<T>(
  scopeKey: string,
  load: (scopeKey: string, signal: AbortSignal) => Promise<T>,
  empty: T,
): ScopedLoad<T> {
  const [boundKey, setBoundKey] = useState(scopeKey);
  const [value, setValue] = useState(empty);
  const [committedKey, setCommittedKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(scopeKey));
  const holder = useRef(createScopeHolder());
  const loadRef = useRef(load);
  const emptyRef = useRef(empty);
  loadRef.current = load;
  emptyRef.current = empty;

  if (boundKey !== scopeKey) {
    setBoundKey(scopeKey);
    setValue(empty);
    setCommittedKey("");
    setError(null);
    setLoading(Boolean(scopeKey));
  }

  // Reload only when scopeKey changes. The loader is read from loadRef so a new function identity does not refetch.
  useEffect(() => {
    const scope = holder.current;
    if (!scopeKey) {
      cancelScopedRequest(scope);
      return;
    }
    const ticket = beginScopedRequest(scope);
    let active = true;
    void loadRef
      .current(scopeKey, ticket.signal)
      .then((data) => {
        if (!active || !ticket.isCurrent()) return;
        setValue(data);
        setCommittedKey(scopeKey);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active || !ticket.isCurrent() || isAbortError(err)) return;
        setValue(emptyRef.current);
        setCommittedKey(scopeKey);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (active && ticket.isCurrent()) setLoading(false);
      });
    return () => {
      active = false;
      cancelScopedRequest(scope);
    };
  }, [scopeKey]);

  return { value, committedKey, error, loading };
}
