import { useCallback, useMemo, useState } from "react";
import { useSiteContext } from "@/contexts/site-context";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { apiFetchText } from "@/lib/api";
import { useRulesList } from "@/hooks/use-rules";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";
import { timeAgo, severityVariant } from "@/lib/utils";
import { useAllEquipment, useEquipment, useSites } from "@/hooks/use-sites";
import {
  useActiveFaults,
  useFaultDefinitions,
  useFaultSummary,
  useSiteFaults,
} from "@/hooks/use-faults";
import { FaultOverTimeChart } from "@/components/dashboard/FaultOverTimeChart";
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

  function sensorFromContext(context: Record<string, unknown> | null | undefined): string {
    if (!context || typeof context !== "object") return "—";
    const c = context as Record<string, unknown>;
    if (typeof c.point_external_id === "string") return c.point_external_id;
    if (typeof c.external_id === "string") return c.external_id;
    if (typeof c.sensor === "string") return c.sensor;
    if (typeof c.column === "string") return c.column;
    return "—";
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {siteMap && <TableHead>Site</TableHead>}
          <TableHead>Device</TableHead>
          <TableHead>Fault</TableHead>
          <TableHead className="text-muted-foreground">Sensor / point</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead className="text-right">Since</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {faults.map((fault) => {
          const def = defMap.get(fault.fault_id);
          const equip = equipMap.get(fault.equipment_id);
          const severity = def?.severity ?? "warning";
          const sensor = sensorFromContext(fault.context);

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
              <TableCell className="text-muted-foreground font-mono text-xs">
                {sensor}
              </TableCell>
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

function FaultDefinitionsSection() {
  const { data: definitions = [], isLoading } = useFaultDefinitions();

  if (isLoading) return <Skeleton className="h-32 w-full rounded-xl" />;
  if (definitions.length === 0) return null;

  return (
    <div className="mb-8">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">
        Fault definitions ({definitions.length})
      </h2>
      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fault ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead className="text-right">Target equipment</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {definitions.map((d) => (
                <TableRow key={d.fault_id}>
                  <TableCell className="font-mono text-xs">{d.fault_id}</TableCell>
                  <TableCell className="font-medium">{d.name}</TableCell>
                  <TableCell className="text-muted-foreground">{d.category ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(d.severity)}>{d.severity}</Badge>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground text-xs">
                    {d.equipment_types?.length ? d.equipment_types.join(", ") : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function faultPeriodRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 7);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function RuleFilesSection() {
  const { data, isLoading } = useRulesList();
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const openFile = useCallback((filename: string) => {
    setSelectedFile(filename);
    setFileContent(null);
    setFileError(null);
    setFileLoading(true);
    apiFetchText(`/rules/${encodeURIComponent(filename)}`)
      .then(setFileContent)
      .catch((e: Error) => setFileError(e.message))
      .finally(() => setFileLoading(false));
  }, []);

  if (isLoading) return <Skeleton className="h-40 w-full rounded-xl" />;
  const files = data?.files ?? [];
  const rulesDir = data?.rules_dir ?? "";

  return (
    <div className="mb-8">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">
        FDD rule files (YAML)
      </h2>
      <p className="mb-2 text-xs text-muted-foreground">
        Rule files on disk (config rules_dir). Fault definitions above come from the database.
      </p>
      <Card>
        <CardContent className="pt-4">
          {data?.error && (
            <p className="mb-3 text-sm text-destructive">{data.error}</p>
          )}
          {rulesDir && (
            <p className="mb-3 font-mono text-xs text-muted-foreground">
              {rulesDir}
            </p>
          )}
          {files.length === 0 && !data?.error ? (
            <p className="text-sm text-muted-foreground">No .yaml files in rules_dir.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {files.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => openFile(name)}
                  className={`rounded-md border px-3 py-1.5 font-mono text-sm transition-colors ${
                    selectedFile === name
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
          )}
          {selectedFile && (
            <div className="mt-4 border-t pt-4">
              <p className="mb-2 font-mono text-xs text-muted-foreground">
                {selectedFile}
              </p>
              {fileLoading && (
                <Skeleton className="h-48 w-full rounded-md" />
              )}
              {fileError && (
                <p className="text-sm text-destructive">{fileError}</p>
              )}
              {fileContent != null && !fileLoading && (
                <pre className="max-h-96 overflow-auto rounded-md border bg-muted/50 p-3 text-xs">
                  {fileContent}
                </pre>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function FaultsPage() {
  const { selectedSiteId } = useSiteContext();
  const [period] = useState(() => faultPeriodRange());
  const { data: definitions = [] } = useFaultDefinitions();
  const { data: summary } = useFaultSummary(
    selectedSiteId ?? undefined,
    period.start,
    period.end,
  );

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Faults</h1>
      <FaultDefinitionsSection />
      <RuleFilesSection />
      {summary != null && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Flagged in period (last 7 d)</p>
              <p
                className={`mt-1 text-3xl font-semibold tabular-nums ${
                  (summary.total_faults ?? 0) > 0 ? "text-destructive" : "text-muted-foreground"
                }`}
              >
                {summary.total_faults ?? 0}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Sum of fault flags in range (matches chart below)
              </p>
            </CardContent>
          </Card>
        </div>
      )}
      <div className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">
          Fault flags over time
        </h2>
        <FaultOverTimeChart siteId={selectedSiteId ?? undefined} definitions={definitions} />
      </div>
      {selectedSiteId ? <SiteFaultsView siteId={selectedSiteId} /> : <AllFaultsView />}
    </div>
  );
}
