import { useMemo } from "react";
import { useSiteContext } from "@/contexts/site-context";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { timeAgo, severityVariant } from "@/lib/utils";
import { useAllEquipment, useEquipment, useSites } from "@/hooks/use-sites";
import { useActiveFaults, useFaultDefinitions, useSiteFaults } from "@/hooks/use-faults";
import type { FaultState, FaultDefinition, Equipment, Site } from "@/types/api";

function FaultsTable({
  faults,
  definitions,
  equipment,
  siteMap,
}: {
  faults: FaultState[];
  definitions: FaultDefinition[];
  equipment: Equipment[];
  siteMap?: Map<string, Site>;
}) {
  const defMap = useMemo(() => new Map(definitions.map((d) => [d.fault_id, d])), [definitions]);
  const equipMap = useMemo(() => new Map(equipment.map((e) => [e.id, e])), [equipment]);

  if (faults.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No active faults{siteMap ? " across any site" : " for this site"}.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {siteMap && <TableHead>Site</TableHead>}
          <TableHead>Equipment</TableHead>
          <TableHead>Fault</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead className="text-right">Since</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {faults.map((fault) => {
          const def = defMap.get(fault.fault_id);
          const equip = equipMap.get(fault.equipment_id);
          const severity = def?.severity ?? "warning";

          return (
            <TableRow key={fault.id}>
              {siteMap && (
                <TableCell className="text-muted-foreground">
                  {siteMap.get(fault.site_id)?.name ?? fault.site_id.slice(0, 8)}
                </TableCell>
              )}
              <TableCell className="font-medium">
                {equip?.name ?? fault.equipment_id.slice(0, 8)}
              </TableCell>
              <TableCell>{def?.name ?? fault.fault_id}</TableCell>
              <TableCell>
                <Badge variant={severityVariant(severity)}>{severity}</Badge>
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                {timeAgo(fault.last_changed_ts)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function AllFaultsView() {
  const { data: faults, isLoading } = useActiveFaults();
  const { data: definitions = [] } = useFaultDefinitions();
  const { data: equipment = [] } = useAllEquipment();
  const { data: sites = [] } = useSites();
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <FaultsTable faults={faults ?? []} definitions={definitions} equipment={equipment} siteMap={siteMap} />
  );
}

function SiteFaultsView({ siteId }: { siteId: string }) {
  const { data: faults = [], isLoading } = useSiteFaults(siteId);
  const { data: definitions = [] } = useFaultDefinitions();
  const { data: equipment = [] } = useEquipment(siteId);

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return <FaultsTable faults={faults} definitions={definitions} equipment={equipment} />;
}

export function FaultsPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Faults</h1>
      {selectedSiteId ? <SiteFaultsView siteId={selectedSiteId} /> : <AllFaultsView />}
    </div>
  );
}
