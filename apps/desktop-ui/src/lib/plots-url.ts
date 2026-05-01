/** Query-string helpers for /plots deep links (FDD overlay, site, join). */

export type PlotsUrlState = {
  siteId: string;
  autoFddOverlay: boolean;
  skipMissingRules: boolean;
  runSource: string;
  joinHow: "inner" | "left" | "outer" | "right";
};

const JOIN: PlotsUrlState["joinHow"][] = ["inner", "left", "outer", "right"];
const SOURCES = ["all", "csv", "weather", "onboard", "bacnet"] as const;

function truthy(v: string | null): boolean {
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

function falsySkipMissing(v: string | null): boolean {
  return v === "0" || v === "false" || v === "no" || v === "off";
}

export function parsePlotsSearch(search: string): Partial<PlotsUrlState> {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const siteId = (params.get("site_id") || params.get("site") || "").trim();
  const autoFddOverlay = truthy(params.get("fdd")) || truthy(params.get("overlay"));
  const skipMissingRules = falsySkipMissing(params.get("skipMissing")) ? false : true;
  const rs = (params.get("runSource") || params.get("source") || "").trim().toLowerCase();
  const runSource = SOURCES.includes(rs as (typeof SOURCES)[number]) ? rs : undefined;
  const jh = (params.get("join") || params.get("joinHow") || "").trim().toLowerCase();
  const joinHow = JOIN.includes(jh as PlotsUrlState["joinHow"]) ? (jh as PlotsUrlState["joinHow"]) : undefined;
  const out: Partial<PlotsUrlState> = {};
  if (siteId) out.siteId = siteId;
  if (autoFddOverlay) out.autoFddOverlay = true;
  out.skipMissingRules = skipMissingRules;
  if (runSource) out.runSource = runSource;
  if (joinHow) out.joinHow = joinHow;
  return out;
}

export function buildPlotsSearch(state: {
  siteId: string;
  autoFddOverlay?: boolean;
  skipMissingRules?: boolean;
  runSource?: string;
  joinHow?: string;
}): string {
  const p = new URLSearchParams();
  if (state.siteId) p.set("site_id", state.siteId);
  if (state.autoFddOverlay) p.set("fdd", "1");
  if (state.skipMissingRules === false) p.set("skipMissing", "0");
  else p.set("skipMissing", "1");
  if (state.runSource) p.set("runSource", state.runSource);
  if (state.joinHow && state.runSource === "all") p.set("join", state.joinHow);
  const s = p.toString();
  return s ? `?${s}` : "";
}
