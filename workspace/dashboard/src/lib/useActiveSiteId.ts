import { useEffect, useState } from "react";
import { apiFetch } from "./api";

/** Active Haystack site from bridge (`/api/model/sites`), not hard-coded demo. */
export function useActiveSiteId(fallback = "site:unknown"): string {
  const [siteId, setSiteId] = useState(fallback);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ active_site_id?: string; sites?: { id: string; site_id?: string }[] }>(
      "/api/model/sites",
    )
      .then((res) => {
        if (cancelled) return;
        const first = res.sites?.[0];
        const sid =
          res.active_site_id || first?.site_id || first?.id || fallback;
        if (sid) setSiteId(sid);
      })
      .catch(() => {
        if (!cancelled && fallback) setSiteId(fallback);
      });
    return () => {
      cancelled = true;
    };
  }, [fallback]);

  return siteId;
}
