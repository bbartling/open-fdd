import { useCallback, useMemo } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router";
import { leaveBuildingSession } from "../api/sessionsApi";
import {
  buildSessionSearch,
  clearEquipmentOnSiteChange,
  parseSessionSearch,
  siteIdLeftBehind,
  type SessionQuery,
} from "./sessionQuery";

/** Read shareable session from URL; patch via navigate (preserves history). */
export function useSessionQuery(): {
  query: SessionQuery;
  setQuery: (patch: Partial<SessionQuery>, replace?: boolean) => void;
} {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();

  const query = useMemo(
    () => parseSessionSearch(params.toString()),
    [params],
  );

  const setQuery = useCallback(
    (patch: Partial<SessionQuery>, replace = false) => {
      const current = parseSessionSearch(location.search);
      const left = siteIdLeftBehind(current, patch);
      if (left) leaveBuildingSession(left);
      const next = buildSessionSearch(
        location.search,
        clearEquipmentOnSiteChange(current, patch),
      );
      navigate({ pathname: location.pathname, search: next }, { replace });
    },
    [location.pathname, location.search, navigate],
  );

  return { query, setQuery };
}
