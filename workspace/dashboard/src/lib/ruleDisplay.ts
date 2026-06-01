/** Strip site-specific prefixes from saved rule names for display in Rule Lab. */

const SITE_PREFIX = /^(?:acme|demo|bens[- ]office|test[- ]bench|bench)\s*[-:]?\s*/i;
const PAREN_TRIM = /\s*\((?:GL36[^)]*|economizer diagnostic|passive poll only)\)\s*/gi;

export function displayRuleName(name: string): string {
  let s = String(name || "").trim();
  s = s.replace(SITE_PREFIX, "");
  s = s.replace(PAREN_TRIM, "");
  s = s.replace(/\bRTU\b/gi, "AHU");
  return s.trim() || "Untitled rule";
}
