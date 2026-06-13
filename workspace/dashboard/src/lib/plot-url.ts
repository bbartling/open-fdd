/** Query-string helpers for /plot deep links (FDD overlay, site, device). */

export type PlotUrlState = {
  siteId: string;
  deviceId: string;
  /** undefined = default on; false = explicitly disabled via ?fdd=0 */
  autoFddOverlay?: boolean;
};

function truthy(v: string | null): boolean {
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

function falsy(v: string | null): boolean {
  return v === "0" || v === "false" || v === "no" || v === "off";
}

export function parsePlotSearch(search: string): Partial<PlotUrlState> {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const siteId = (params.get("site_id") || params.get("site") || "").trim();
  const deviceId = (params.get("device_id") || params.get("device") || "").trim();
  const fddParam = params.get("fdd") ?? params.get("overlay");
  const out: Partial<PlotUrlState> = {};
  if (siteId) out.siteId = siteId;
  if (deviceId) out.deviceId = deviceId;
  if (fddParam != null) {
    if (truthy(fddParam)) out.autoFddOverlay = true;
    else if (falsy(fddParam)) out.autoFddOverlay = false;
  }
  return out;
}
