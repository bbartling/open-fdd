import { useCallback, useMemo } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router";
import {
  buildSessionSearch,
  parseSessionSearch,
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
      const next = buildSessionSearch(location.search, patch);
      navigate({ pathname: location.pathname, search: next }, { replace });
    },
    [location.pathname, location.search, navigate],
  );

  return { query, setQuery };
}
