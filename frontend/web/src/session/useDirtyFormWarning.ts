import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Track dirty form state and warn on browser unload / optional in-app leave.
 * Does not persist domain authority — drafts only.
 */
export function useDirtyFormWarning(dirty: boolean, message?: string) {
  const msg =
    message ?? "You have unsaved changes. Leave this page and discard them?";
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      e.preventDefault();
      e.returnValue = msg;
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [msg]);

  const confirmLeave = useCallback(() => {
    if (!dirtyRef.current) return true;
    return window.confirm(msg);
  }, [msg]);

  return { confirmLeave };
}

export function useFormDraft<T extends Record<string, unknown>>(
  key: string,
  initial: T,
): [T, (next: T | ((prev: T) => T)) => void, () => void, boolean] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(`openfdd.formDraft.${key}`);
      if (raw) return { ...initial, ...(JSON.parse(raw) as T) };
    } catch {
      // ignore
    }
    return initial;
  });
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) return;
    sessionStorage.setItem(`openfdd.formDraft.${key}`, JSON.stringify(value));
  }, [key, value, dirty]);

  const update = useCallback((next: T | ((prev: T) => T)) => {
    setValue((prev) => (typeof next === "function" ? next(prev) : next));
    setDirty(true);
  }, []);

  const clear = useCallback(() => {
    sessionStorage.removeItem(`openfdd.formDraft.${key}`);
    setValue(initial);
    setDirty(false);
  }, [key, initial]);

  return [value, update, clear, dirty];
}
