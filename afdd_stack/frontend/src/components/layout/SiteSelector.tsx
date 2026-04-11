import { useState, useRef, useEffect } from "react";
import { ChevronsUpDown, Check } from "lucide-react";
import { useSites } from "@/hooks/use-sites";
import { useSiteContext } from "@/contexts/site-context";

export function SiteSelector() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const { data: sites = [] } = useSites();
  const { selectedSiteId, setSelectedSiteId, selectedSite } = useSiteContext();

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const lowerSearch = search.toLowerCase();
  const filtered = sites.filter(
    (s) =>
      !search ||
      s.name.toLowerCase().includes(lowerSearch) ||
      (s.description?.toLowerCase().includes(lowerSearch) ?? false),
  );

  function select(id: string | null) {
    setSelectedSiteId(id);
    setOpen(false);
    setSearch("");
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="listbox"
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-border/60 bg-background px-3 text-sm font-medium transition-colors duration-150 hover:bg-muted/50"
        onClick={() => setOpen(!open)}
      >
        {selectedSite?.name ?? "All Sites"}
        <ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute left-0 z-50 mt-2 w-72 rounded-2xl border border-border/60 bg-card/95 shadow-xl shadow-black/[0.08] backdrop-blur-lg">
          <div className="border-b border-border/60 p-2.5">
            <input
              type="text"
              placeholder="Search sites\u2026"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm transition-colors duration-200 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              autoFocus
            />
          </div>

          <div className="max-h-64 overflow-y-auto p-1.5">
            {/* All Sites option */}
            <button
              type="button"
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 hover:bg-muted/50"
              onClick={() => select(null)}
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                {!selectedSiteId && (
                  <Check className="h-3.5 w-3.5 text-foreground" />
                )}
              </span>
              <span className="font-medium">All Sites</span>
            </button>

            {filtered.map((site) => (
              <button
                key={site.id}
                type="button"
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 hover:bg-muted/50"
                onClick={() => select(site.id)}
              >
                <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                  {selectedSiteId === site.id && (
                    <Check className="h-3.5 w-3.5 text-foreground" />
                  )}
                </span>
                <span className="truncate">{site.name}</span>
              </button>
            ))}

            {filtered.length === 0 && (
              <p className="px-2.5 py-4 text-center text-sm text-muted-foreground">
                No sites found
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
