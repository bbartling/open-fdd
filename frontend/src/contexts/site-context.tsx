import { createContext, useContext, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useSite } from "@/hooks/use-sites";
import type { Site } from "@/types/api";

interface SiteContextValue {
  selectedSiteId: string | null;
  setSelectedSiteId: (id: string | null) => void;
  selectedSite: Site | undefined;
}

const SiteContext = createContext<SiteContextValue | null>(null);

export function SiteProvider({ children }: { children: React.ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedSiteId = searchParams.get("site");

  const { data: selectedSite } = useSite(selectedSiteId ?? undefined);

  const setSelectedSiteId = useCallback(
    (id: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id) {
            next.set("site", id);
          } else {
            next.delete("site");
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return (
    <SiteContext.Provider
      value={{ selectedSiteId, setSelectedSiteId, selectedSite }}
    >
      {children}
    </SiteContext.Provider>
  );
}

export function useSiteContext() {
  const ctx = useContext(SiteContext);
  if (!ctx) throw new Error("useSiteContext must be used within SiteProvider");
  return ctx;
}
