/** User display preference (independent of SI storage / processing ABI). */

export type DisplayPreference = "imperial" | "metric";

/** @deprecated use DisplayPreference */
export type UnitSystem = DisplayPreference;

export const DISPLAY_PREFERENCE_KEY = "openfdd.ui.display_units";

/** Imperial default for US English locales; SI (metric) otherwise. */
export function defaultDisplayPreference(): DisplayPreference {
  if (typeof navigator !== "undefined") {
    const lang = navigator.language ?? "";
    if (/^en-US\b/i.test(lang)) return "imperial";
  }
  return "metric";
}

export function readDisplayPreference(): DisplayPreference {
  if (typeof localStorage === "undefined") return defaultDisplayPreference();
  const raw = localStorage.getItem(DISPLAY_PREFERENCE_KEY);
  if (raw === "metric") return "metric";
  if (raw === "imperial") return "imperial";
  return defaultDisplayPreference();
}

export function writeDisplayPreference(preference: DisplayPreference): void {
  localStorage.setItem(DISPLAY_PREFERENCE_KEY, preference);
}
