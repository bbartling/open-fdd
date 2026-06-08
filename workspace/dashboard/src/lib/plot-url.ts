/** Query-string helpers for /plot deep links (FDD overlay, site, device). */

export type PlotUrlState = {
  siteId: string;
  deviceId: string;
  autoFddOverlay: boolean;
};

function truthy(v: string | null): boolean {
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

export function parsePlotSearch(search: string): Partial<PlotUrlState> {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const siteId = (params.get("site_id") || params.get("site") || "").trim();
  const deviceId = (params.get("device_id") || params.get("device") || "").trim();
  const autoFddOverlay = truthy(params.get("fdd")) || truthy(params.get("overlay"));
  const out: Partial<PlotUrlState> = {};
  if (siteId) out.siteId = siteId;
  if (deviceId) out.deviceId = deviceId;
  if (autoFddOverlay) out.autoFddOverlay = true;
  return out;
}
