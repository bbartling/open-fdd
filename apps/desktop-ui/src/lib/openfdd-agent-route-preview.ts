/**
 * Client-side preview of SIMPLE vs COMPLEX routing for the built-in agent.
 * Mirrors `open_fdd.gateway.openfdd_agent_routing.classify_openfdd_task` (keep patterns in sync).
 * The bridge may still choose differently when `OFDD_CODEX_LLM_CLASSIFY=1` or `OFDD_AGENT_ROUTE_DEFAULT=complex`.
 */

export type TaskTierPreview = "simple" | "complex";

const COMPLEX_PATTERNS: [RegExp, string][] = [
  [/\brace condition\b/i, "race / timing"],
  [/\btiming[- ]dependent\b/i, "timing-dependent"],
  [/\bsecurity\b|\bvulnerab/i, "security"],
  [/\bperformance\b|\bdegradation\b/i, "performance"],
  [/\bambiguous\b|\broot cause\b/i, "ambiguous / root cause"],
  [/\b(span|spans)\b.{0,40}\b(component|file|service|subsystem)/i, "multi-component"],
  [/\b(multi[- ]site|cross[- ]site|all sites)\b/i, "multi-site"],
  [/\b(brick|sparql|ttl)\b.{0,40}\b(import|export|merge|refactor)/i, "BRICK/SPARQL/TTL redesign"],
  [/\brule pack\b.{0,40}\b(redesign|overhaul|architecture)/i, "rule architecture"],
  [/\bingest\b.{0,40}\b(pipeline|architecture|redesign)/i, "ingest architecture"],
  [/\bunexpected\b.{0,40}\b(pass|passed)\b/i, "unexpected pass"],
];

const SIMPLE_PATTERNS: [RegExp, string][] = [
  [/\bpass\/fail\b/i, "pass/fail"],
  [/\bhttp\b.{0,30}\b(404|500|502|503|timeout)\b/i, "HTTP status / timeout"],
  [/\bmissing\b.{0,30}\b(ui|selector|element)\b/i, "missing UI"],
  [/\bsetup failure\b|\benv(ironment)?\b.{0,20}\b(wrong|missing)\b/i, "setup / env"],
  [/\bsyntax error\b|\bimport failure\b|\bmodulenotfound/i, "syntax / import"],
  [/\b(get|post)\s+\/\s*health\b|\b\/health\b/i, "health check"],
  [/\blist sites\b|\bget\s+\/sites\b/i, "list sites"],
  [/\bsingle (csv|file|column)\b/i, "single artifact"],
  [/\b(one[- ]liner|quick check|trivial)\b/i, "explicitly trivial"],
];

/** Default SIMPLE unless text matches COMPLEX, or matches SIMPLE explicitly. If both match, COMPLEX wins. */
export function classifyOpenfddTaskPreview(taskSummary: string, defaultTier: TaskTierPreview = "simple"): TaskTierPreview {
  const text = String(taskSummary || "")
    .trim()
    .toLowerCase();
  if (!text) {
    return defaultTier;
  }
  for (const [re] of COMPLEX_PATTERNS) {
    if (re.test(text)) {
      return "complex";
    }
  }
  for (const [re] of SIMPLE_PATTERNS) {
    if (re.test(text)) {
      return "simple";
    }
  }
  return defaultTier;
}
