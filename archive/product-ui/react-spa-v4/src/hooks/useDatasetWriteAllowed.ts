import { useEffect, useState } from "react";
import { getAuthMe } from "../api/authApi";

/**
 * True when the signed-in role may import, append, or delete a site.
 * Starts false so a read-only session does not flash write controls.
 */
export function useDatasetWriteAllowed(): boolean {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getAuthMe()
      .then((me) => {
        if (cancelled || !me) return;
        const role = me.role;
        setAllowed(role === "operator" || role === "admin");
      })
      .catch(() => {
        if (!cancelled) setAllowed(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return allowed;
}
