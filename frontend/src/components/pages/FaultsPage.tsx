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
import { useAllEquipment, useEquipment, useSite, useSites } from "@/hooks/use-sites";
import {
  useActiveFaults,
  useFaultDefinitions,
  useFaultSummary,
  useFaultState,
  useBacnetDevices,
  useSiteFaults,
} from "@/hooks/use-faults";
import { FaultOverTimeChart } from "@/components/dashboard/FaultOverTimeChart";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import type { FaultState, FaultDefinition, Equipment, Site, BacnetDevice } from "@/types/api";
import {
  computeFaultMatrixCellStatus,
  matrixCellKey,
} from "@/components/pages/fault-matrix-utils";

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
  const equipById = useMemo(() => new Map(equipment.map((e) => [e.id, e])), [equipment]);
  const equipByName = useMemo(() => new Map(equipment.map((e) => [e.name, e])), [equipment]);
  const siteNames = useMemo(() => new Set(siteMap ? Array.from(siteMap.values()).map((s) => s.name) : []), [siteMap]);

  function deviceLabel(fault: FaultState): string {
    const equip = equipById.get(fault.equipment_id) ?? equipByName.get(fault.equipment_id);
    const base = equip ? equip.name : (siteMap && siteNames.has(fault.equipment_id) ? `Site: ${fault.equipment_id}` : fault.equipment_id);
    if (fault.bacnet_device_id != null && fault.bacnet_device_id !== "") {
      return `${base} (BACnet ${fault.bacnet_device_id})`;
    }
    return base;
  }

  if (faults.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center" data-testid="faults-empty-state">
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
    <Table data-testid="faults-active-table">
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
                {deviceLabel(fault)}
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

function FaultMatrixTable({
  devices,
  definitions,
  state,
  siteMap,
}: {
  devices: BacnetDevice[];
  definitions: FaultDefinition[];
  state: FaultState[];
  siteMap?: Map<string, Site>;
}) {
  const cellStatus = useMemo(
    () => computeFaultMatrixCellStatus(devices, definitions, state),
    [devices, definitions, state],
  );

  if (devices.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground" data-testid="fault-matrix-empty">
        No BACnet devices in data model. Add points with bacnet_device_id (and equipment) to see the matrix.
      </div>
    );
  }

  if (definitions.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        No fault definitions. Add rule YAML files to rules_dir (platform config); each FDD run syncs them into the DB.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table data-testid="fault-matrix-table">
        <TableHeader>
          <TableRow>
            <TableHead className="font-mono">BACnet device</TableHead>
            <TableHead>Equipment</TableHead>
            {siteMap && <TableHead>Site</TableHead>}
            {definitions.map((d) => (
              <TableHead key={d.fault_id} className="text-center font-medium">
                {d.name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {devices.map((dev) => (
            <TableRow key={`${dev.site_id}-${dev.bacnet_device_id}`}>
              <TableCell className="font-mono">{dev.bacnet_device_id}</TableCell>
              <TableCell>{dev.equipment_name}</TableCell>
              {siteMap && (
                <TableCell className="text-muted-foreground">
                  {siteMap.get(dev.site_id)?.name ?? dev.site_name}
                </TableCell>
              )}
              {definitions.map((def) => {
                const key = matrixCellKey(dev, def.fault_id);
                const status = cellStatus.get(key) ?? "n_a";
                return (
                  <TableCell key={def.fault_id} className="text-center">
                    {status === "active" && (
                      <Badge variant="destructive" className="font-normal">Active</Badge>
                    )}
                    {status === "not_active" && (
                      <span className="text-muted-foreground">Not active</span>
                    )}
                    {status === "n_a" && (
                      <span className="text-muted-foreground/70">N/A</span>
                    )}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
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
  const { data: site } = useSite(siteId);
  const siteMap = useMemo(
    () => (site ? new Map([[site.id, site]]) : undefined),
    [site],
  );

  if (isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />;

  return (
    <FaultsTable
      faults={faults}
      definitions={definitions}
      equipment={equipment}
      siteMap={siteMap}
    />
  );
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

function formatLocalDT(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}`;
}

function presetRange(preset: DatePreset): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (preset) {
    case "24h":
      start.setHours(start.getHours() - 24);
      break;
    case "7d":
      start.setDate(start.getDate() - 7);
      break;
    case "30d":
      start.setDate(start.getDate() - 30);
      break;
    default:
      start.setDate(start.getDate() - 7);
  }
  return { start: start.toISOString(), end: end.toISOString() };
}

function labelForPreset(preset: DatePreset): string {
  switch (preset) {
    case "24h":
      return "last 24 h";
    case "7d":
      return "last 7 d";
    case "30d":
      return "last 30 d";
    case "custom":
    default:
      return "custom range";
  }
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
        Rule YAML from platform config (rules_dir via GET /config). FDD loop loads from disk each run—hot reload for fault tuning. Definitions above from database.
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
  const [preset, setPreset] = useState<DatePreset>("7d");
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const [customStart, setCustomStart] = useState(formatLocalDT(weekAgo));
  const [customEnd, setCustomEnd] = useState(formatLocalDT(now));

  const { start, end } = useMemo(() => {
    if (preset === "custom") {
      return {
        start: new Date(customStart).toISOString(),
        end: new Date(customEnd).toISOString(),
      };
    }
    return presetRange(preset);
  }, [preset, customStart, customEnd]);

  const bucket: "hour" | "day" = preset === "24h" ? "hour" : "day";
  const { data: definitions = [] } = useFaultDefinitions();
  const { data: summary } = useFaultSummary(
    selectedSiteId ?? undefined,
    start,
    end,
  );
  const periodLabel = labelForPreset(preset);

  const { data: devices = [] } = useBacnetDevices(selectedSiteId ?? undefined);
  const { data: faultState = [] } = useFaultState(selectedSiteId ?? undefined);
  const { data: sites = [] } = useSites();
  const { data: site } = useSite(selectedSiteId ?? "");
  const matrixSiteMap = useMemo(() => {
    if (selectedSiteId && site) return new Map([[site.id, site]]);
    return new Map(sites.map((s) => [s.id, s]));
  }, [selectedSiteId, site, sites]);

  return (
    <div className="flex flex-col">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">Faults</h1>

      {/* Time range bar at top: all summary and charts below use this range */}
      <header className="mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-border/80 bg-muted/70 px-4 py-3 shadow-sm">
        <span className="text-sm font-semibold text-foreground">Time range</span>
        <DateRangeSelect
          preset={preset}
          onPresetChange={setPreset}
          customStart={customStart}
          customEnd={customEnd}
          onCustomStartChange={setCustomStart}
          onCustomEndChange={setCustomEnd}
        />
        <span className="font-mono text-sm text-muted-foreground tabular-nums">
          {start.slice(0, 10)} → {end.slice(0, 10)}
        </span>
      </header>

      {summary != null && (
        <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Active faults in period ({periodLabel})</p>
              <p
                className={`mt-1 text-3xl font-semibold tabular-nums ${
                  (summary.active_in_period ?? summary.total_faults ?? 0) > 0
                    ? "text-destructive"
                    : "text-muted-foreground"
                }`}
              >
                {summary.active_in_period ?? summary.total_faults ?? 0}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Distinct (site + device + fault) in range. From FDD rule runs (fault_results).
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Fault flags over time</h2>
        <FaultOverTimeChart
          siteId={selectedSiteId ?? undefined}
          definitions={definitions}
          preset={preset}
          start={start}
          end={end}
          bucket={bucket}
        />
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">
          BACnet devices × fault definitions (from data model + rule YAML)
        </h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Rows = BACnet devices (data model). Cols = faults from rule YAML in rules_dir (platform config). Fault definitions auto-populate when you add or edit .yaml files in that dir—each FDD run syncs them to the DB. Active = fault currently active; Not active = applies but clear; N/A = fault does not apply to this device (equipment_type).
        </p>
        <Card>
          <CardContent className="pt-4">
            <FaultMatrixTable
              devices={devices}
              definitions={definitions}
              state={faultState}
              siteMap={matrixSiteMap}
            />
          </CardContent>
        </Card>
      </section>

      <FaultDefinitionsSection />
      <RuleFilesSection />

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Active fault rows (current state)</h2>
        {selectedSiteId ? <SiteFaultsView siteId={selectedSiteId} /> : <AllFaultsView />}
      </section>
    </div>
  );
}
