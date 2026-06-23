import { useEffect, useState } from "react";
import { apiFetch } from "./api";

/** Active BRICK site from bridge (`/api/model/sites`), not hard-coded demo. */
export function useActiveSiteId(fallback = ""): string {
  const [siteId, setSiteId] = useState(fallback);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ active_site_id?: string; sites?: { id: string }[] }>("/api/model/sites")
      .then((res) => {
        if (cancelled) return;
        const first = res.sites?.[0] as { id?: string; site_id?: string } | undefined;
        const sid = res.active_site_id || first?.id || first?.site_id || fallback;
        if (sid) setSiteId(sid);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [fallback]);

  return siteId;
}
