/**
 * Sidebar collapse + narrow-viewport layout helpers (UI-403-05).
 * Pure storage/layout decisions so Vitest can cover them without a live stack.
 */

export const SIDEBAR_COLLAPSED_KEY = "openfdd.ui.sidebar_collapsed";

/** Matches `.app-shell--sidebar-narrow` media query in `styles/app.css`. */
export const SIDEBAR_NARROW_MQ = "(max-width: 768px)";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

export function readCollapsedPreference(
  storage: StorageLike | null | undefined = defaultStorage(),
): boolean | null {
  if (!storage) return null;
  try {
    const v = storage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (v === "1" || v === "true") return true;
    if (v === "0" || v === "false") return false;
    return null;
  } catch {
    return null;
  }
}

export function writeCollapsedPreference(
  collapsed: boolean,
  storage: StorageLike | null | undefined = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    /* private mode / quota */
  }
}

/**
 * Sensible first paint: keep the working surface open on a narrow viewport
 * unless the operator already chose expand/collapse.
 */
export function initialCollapsed(
  isNarrow: boolean,
  storage: StorageLike | null | undefined = defaultStorage(),
): boolean {
  const pref = readCollapsedPreference(storage);
  if (pref != null) return pref;
  return isNarrow;
}

export type SidebarViewportMode = "wide" | "narrow";

export interface SidebarShellFlags {
  mode: SidebarViewportMode;
  /** Expanded on a narrow viewport — share the row; never cover main. */
  narrowExpanded: boolean;
  classNames: string[];
}

export function sidebarShellFlags(input: {
  collapsed: boolean;
  isNarrow: boolean;
}): SidebarShellFlags {
  const mode: SidebarViewportMode = input.isNarrow ? "narrow" : "wide";
  const narrowExpanded = input.isNarrow && !input.collapsed;
  const classNames = [
    input.collapsed ? "app-shell--sidebar-collapsed" : "",
    input.isNarrow ? "app-shell--sidebar-narrow" : "",
    narrowExpanded ? "app-shell--sidebar-narrow-expanded" : "",
  ].filter(Boolean);
  return { mode, narrowExpanded, classNames };
}

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
