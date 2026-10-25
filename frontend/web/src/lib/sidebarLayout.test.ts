import { describe, expect, it } from "vitest";
import {
  initialCollapsed,
  readCollapsedPreference,
  SIDEBAR_COLLAPSED_KEY,
  sidebarShellFlags,
  writeCollapsedPreference,
} from "./sidebarLayout";

function memoryStorage(seed: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(seed));
  return {
    get length() {
      return map.size;
    },
    clear() {
      map.clear();
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null;
    },
    key(index: number) {
      return [...map.keys()][index] ?? null;
    },
    removeItem(key: string) {
      map.delete(key);
    },
    setItem(key: string, value: string) {
      map.set(key, String(value));
    },
  };
}

describe("sidebar collapse preference", () => {
  it("round-trips collapse state for reload persistence", () => {
    const storage = memoryStorage();
    expect(readCollapsedPreference(storage)).toBeNull();
    writeCollapsedPreference(true, storage);
    expect(storage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("1");
    expect(readCollapsedPreference(storage)).toBe(true);
    writeCollapsedPreference(false, storage);
    expect(readCollapsedPreference(storage)).toBe(false);
  });

  it("defaults to collapsed on a narrow viewport when nothing is stored", () => {
    expect(initialCollapsed(true, memoryStorage())).toBe(true);
    expect(initialCollapsed(false, memoryStorage())).toBe(false);
  });

  it("honors a stored expand choice even on a narrow viewport", () => {
    const storage = memoryStorage({ [SIDEBAR_COLLAPSED_KEY]: "0" });
    expect(initialCollapsed(true, storage)).toBe(false);
  });

  it("honors a stored collapse choice on a wide viewport", () => {
    const storage = memoryStorage({ [SIDEBAR_COLLAPSED_KEY]: "1" });
    expect(initialCollapsed(false, storage)).toBe(true);
  });
});

describe("wide versus narrow shell flags", () => {
  it("marks a narrow expanded shell without collapsing", () => {
    const flags = sidebarShellFlags({ collapsed: false, isNarrow: true });
    expect(flags.mode).toBe("narrow");
    expect(flags.narrowExpanded).toBe(true);
    expect(flags.classNames).toContain("app-shell--sidebar-narrow");
    expect(flags.classNames).toContain("app-shell--sidebar-narrow-expanded");
    expect(flags.classNames).not.toContain("app-shell--sidebar-collapsed");
  });

  it("keeps wide expanded chrome free of narrow flags", () => {
    const flags = sidebarShellFlags({ collapsed: false, isNarrow: false });
    expect(flags.mode).toBe("wide");
    expect(flags.narrowExpanded).toBe(false);
    expect(flags.classNames).toEqual([]);
  });

  it("collapses on either viewport without the narrow-expanded flag", () => {
    expect(
      sidebarShellFlags({ collapsed: true, isNarrow: true }).narrowExpanded,
    ).toBe(false);
    expect(
      sidebarShellFlags({ collapsed: true, isNarrow: false }).classNames,
    ).toEqual(["app-shell--sidebar-collapsed"]);
  });
});
