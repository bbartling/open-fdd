import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";

export type Site = {
  id: string;
  name: string;
};

type SiteContextValue = {
  sites: Site[];
  selectedSiteId: string;
  setSelectedSiteId: (siteId: string) => void;
  refreshSites: () => Promise<Site[]>;
};

const SiteContext = createContext<SiteContextValue | null>(null);

export function SiteProvider({ children }: { children: React.ReactNode }) {
  const [sites, setSites] = useState<Site[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState("");
  const refreshReqIdRef = useRef(0);

  const refreshSites = useCallback(async () => {
    refreshReqIdRef.current += 1;
    const requestId = refreshReqIdRef.current;
    const next = await desktopFetch<Site[]>("/sites");
    if (requestId !== refreshReqIdRef.current) {
      return [];
    }
    setSites(next);
    if (next.length === 0) {
      setSelectedSiteId("");
      return next;
    }
    setSelectedSiteId((current) => {
      if (current && next.some((site) => site.id === current)) {
        return current;
      }
      return next[0].id;
    });
    return next;
  }, []);

  useEffect(() => {
    void refreshSites().catch(() => {
      setSites([]);
      setSelectedSiteId("");
    });
  }, [refreshSites]);

  const value = useMemo(
    () => ({
      sites,
      selectedSiteId,
      setSelectedSiteId,
      refreshSites,
    }),
    [sites, selectedSiteId, refreshSites],
  );

  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>;
}

export function useSite() {
  const value = useContext(SiteContext);
  if (!value) {
    throw new Error("useSite must be used within SiteProvider");
  }
  return value;
}

export function useOptionalSite() {
  return useContext(SiteContext);
}
