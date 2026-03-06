import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSiteContext } from "@/contexts/site-context";
import { Skeleton } from "@/components/ui/skeleton";
import { useAllPoints, useAllEquipment, usePoints, useEquipment, useSites } from "@/hooks/use-sites";
import { useTimeseriesLatest } from "@/hooks/use-timeseries-latest";
import { PointsTree } from "@/components/site/PointsTree";
import { BacnetDiscoveryPanel } from "@/components/site/BacnetDiscoveryPanel";
import { deletePoint, deleteEquipment, deleteSite } from "@/lib/crud-api";

function useTreeMutations() {
  const queryClient = useQueryClient();
  const deletePointMutation = useMutation({
    mutationFn: deletePoint,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });
  const deleteEquipmentMutation = useMutation({
    mutationFn: deleteEquipment,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });
  const deleteSiteMutation = useMutation({
    mutationFn: deleteSite,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });
  return {
    onDeletePoint: (id: string) => {
      if (window.confirm("Delete this point? Timeseries for this point will be removed.")) {
        deletePointMutation.mutate(id);
      }
    },
    onDeleteEquipment: (id: string, name: string) => {
      if (window.confirm(`Delete equipment "${name}"? This will delete all points under it.`)) {
        deleteEquipmentMutation.mutate(id);
      }
    },
    onDeleteSite: (id: string, name: string) => {
      if (window.confirm(`Delete site "${name}"? This removes all equipment, points, timeseries, and faults.`)) {
        deleteSiteMutation.mutate(id);
      }
    },
  };
}

function AllPointsView() {
  const treeMutations = useTreeMutations();
  const { data: points, isLoading } = useAllPoints();
  const { data: equipment = [] } = useAllEquipment();
  const { data: sites = [] } = useSites();
  const { data: latestList = [] } = useTimeseriesLatest(undefined);
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);
  const latestByPointId = useMemo(
    () =>
      new Map(
        latestList.map((r) => [r.point_id, { value: r.value, ts: r.ts }]),
      ),
    [latestList],
  );

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <PointsTree
      points={points ?? []}
      equipment={equipment}
      siteMap={siteMap}
      latestByPointId={latestByPointId}
      {...treeMutations}
    />
  );
}

function SitePointsView({ siteId }: { siteId: string }) {
  const treeMutations = useTreeMutations();
  const { data: points = [], isLoading } = usePoints(siteId);
  const { data: equipment = [] } = useEquipment(siteId);
  const { data: latestList = [] } = useTimeseriesLatest(siteId);
  const latestByPointId = useMemo(
    () =>
      new Map(
        latestList.map((r) => [r.point_id, { value: r.value, ts: r.ts }]),
      ),
    [latestList],
  );

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <PointsTree
      points={points}
      equipment={equipment}
      latestByPointId={latestByPointId}
      {...treeMutations}
    />
  );
}

export function PointsPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">Points</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Polling (data model) indicates whether the BACnet scraper polls this point; last value and time come from
        timeseries. Use BACnet discovery below to run Who-Is, point discovery, and add devices to the data model. Right-click tree nodes to delete.
      </p>
      <BacnetDiscoveryPanel />
      {selectedSiteId ? <SitePointsView siteId={selectedSiteId} /> : <AllPointsView />}
    </div>
  );
}
