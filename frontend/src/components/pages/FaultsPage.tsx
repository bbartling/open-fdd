import { useSiteContext } from "@/contexts/site-context";
import { FaultsTab } from "@/components/site/FaultsTab";
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
import { useAllEquipment, useEquipment } from "@/hooks/use-sites";
import { useActiveFaults, useFaultDefinitions, useSiteFaults } from "@/hooks/use-faults";
import { useSites } from "@/hooks/use-sites";

function AllFaultsView() {
  const { data: faults, isLoading } = useActiveFaults();
  const { data: definitions = [] } = useFaultDefinitions();
  const { data: equipment = [] } = useAllEquipment();
  const { data: sites = [] } = useSites();

  if (isLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  if (!faults || faults.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No active faults across any site.
        </p>
      </div>
    );
  }

  const defMap = new Map(definitions.map((d) => [d.fault_id, d]));
  const equipMap = new Map(equipment.map((e) => [e.id, e]));
  const siteMap = new Map(sites.map((s) => [s.id, s]));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Site</TableHead>
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
          const siteName = siteMap.get(fault.site_id)?.name ?? fault.site_id.slice(0, 8);

          return (
            <TableRow key={fault.id}>
              <TableCell className="text-muted-foreground">{siteName}</TableCell>
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

function SiteFaultsView({ siteId }: { siteId: string }) {
  const { data: faults = [], isLoading } = useSiteFaults(siteId);
  const { data: definitions = [] } = useFaultDefinitions();
  const { data: equipment = [] } = useEquipment(siteId);

  if (isLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  return <FaultsTab faults={faults} definitions={definitions} equipment={equipment} />;
}

export function FaultsPage() {
  const { selectedSiteId } = useSiteContext();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Faults</h1>
      {selectedSiteId ? (
        <SiteFaultsView siteId={selectedSiteId} />
      ) : (
        <AllFaultsView />
      )}
    </div>
  );
}
