import { useRef } from "react";

/**
 * Whether this render should send `refresh: true` to the analytics cache.
 *
 * Overview does not use this hook. Overview refresh goes through
 * `overviewQueryPolicy`: opening a site does not recompute, and a single
 * rule completion recomputes only the queries that include that rule.
 *
 * Opening a building uses the cache. A later `refreshToken` change for that
 * same building is an explicit operator refetch. Switching buildings clears it.
 *
 * The flag stays true across a strict-mode effect remount so the cancelled
 * first fetch and the follow-up fetch both recompute.
 */
export function useExplicitAnalyticsRefresh(
  buildingId: string,
  refreshToken: number,
): boolean {
  const wantsRefresh = useRef(false);
  const seen = useRef({ buildingId, refreshToken });
  if (seen.current.buildingId !== buildingId) {
    wantsRefresh.current = false;
    seen.current = { buildingId, refreshToken };
  } else if (seen.current.refreshToken !== refreshToken) {
    wantsRefresh.current = true;
    seen.current = { buildingId, refreshToken };
  }
  return wantsRefresh.current;
}
