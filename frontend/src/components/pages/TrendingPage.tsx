import { TrendingUp } from "lucide-react";
import { useSiteContext } from "@/contexts/site-context";
import { TrendingTab } from "@/components/site/TrendingTab";
import { Skeleton } from "@/components/ui/skeleton";
import { useEquipment, usePoints } from "@/hooks/use-sites";

function SiteTrendingView({ siteId }: { siteId: string }) {
  const { data: points = [], isLoading: ptsLoading } = usePoints(siteId);
  const { data: equipment = [], isLoading: eqLoading } = useEquipment(siteId);

  if (ptsLoading || eqLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  return <TrendingTab siteId={siteId} points={points} equipment={equipment} />;
}

export function TrendingPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Trending</h1>
      {selectedSiteId ? (
        <SiteTrendingView siteId={selectedSiteId} />
      ) : (
        <div className="flex h-72 flex-col items-center justify-center rounded-2xl border border-border/60 bg-card">
          <TrendingUp className="mb-3 h-8 w-8 text-muted-foreground/60" />
          <p className="text-sm font-medium text-foreground">
            Select a site to view trending data
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Use the site selector in the top bar to choose a site.
          </p>
        </div>
      )}
    </div>
  );
}
