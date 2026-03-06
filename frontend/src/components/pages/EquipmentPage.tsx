import { useMemo } from "react";
import { useSiteContext } from "@/contexts/site-context";
import { Skeleton } from "@/components/ui/skeleton";
import { useAllEquipment, useAllPoints, useEquipment, usePoints, useSites } from "@/hooks/use-sites";
import { useActiveFaults, useSiteFaults } from "@/hooks/use-faults";
import { EquipmentTable } from "@/components/site/EquipmentTable";

function AllEquipmentView() {
  const { data: equipment, isLoading } = useAllEquipment();
  const { data: points = [] } = useAllPoints();
  const { data: faults = [] } = useActiveFaults();
  const { data: sites = [] } = useSites();
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <EquipmentTable
      equipment={equipment ?? []}
      points={points}
      faults={faults}
      siteMap={siteMap}
    />
  );
}

function SiteEquipmentView({ siteId }: { siteId: string }) {
  const { data: equipment = [], isLoading } = useEquipment(siteId);
  const { data: points = [] } = usePoints(siteId);
  const { data: faults = [] } = useSiteFaults(siteId);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return <EquipmentTable equipment={equipment} points={points} faults={faults} />;
}

export function EquipmentPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Equipment</h1>
      {selectedSiteId ? <SiteEquipmentView siteId={selectedSiteId} /> : <AllEquipmentView />}
    </div>
  );
}
