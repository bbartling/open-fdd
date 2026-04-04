import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useSiteContext } from "@/contexts/site-context";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { apiFetchText } from "@/lib/api";
import { useRulesList } from "@/hooks/use-rules";
import { uploadRule, deleteRule, syncRuleDefinitions } from "@/lib/crud-api";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";
import { JsonPrettyPanel } from "@/components/ui/json-pretty-panel";
import { timeAgo, severityVariant } from "@/lib/utils";
import { useAllEquipment, useEquipment, useSite, useSites } from "@/hooks/use-sites";
import {
  useActiveFaults,
  useFaultDefinitions,
  useFaultSummary,
  useFaultState,
  useBacnetDevices,
  useSiteFaults,
  useFaultResultsSeries,
  useFaultResultsRaw,
} from "@/hooks/use-faults";
import { FaultOverTimeChart } from "@/components/dashboard/FaultOverTimeChart";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import type { FaultState, FaultDefinition, Equipment, Site, BacnetDevice } from "@/types/api";
import {
  computeFaultMatrixCellStatus,
  computeDeviceLastFaultTs,
  deviceRowKey,
  matrixCellKey,
} from "@/components/pages/fault-matrix-utils";
import { isHotReloadBenchArtifact } from "@/lib/rule-files";

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
          <TableHead className="w-[1%] whitespace-nowrap text-muted-foreground">Plots</TableHead>
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
              <TableCell>
                {fault.bacnet_device_id != null && fault.bacnet_device_id !== "" ? (
                  <Link
                    className="text-xs text-primary underline-offset-2 hover:underline"
                    to={`/plots?${new URLSearchParams({
                      site: fault.site_id,
                      device: fault.bacnet_device_id,
                      fault: fault.fault_id,
                    }).toString()}`}
                  >
                    Trends
                  </Link>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
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
  const lastFaultByDevice = useMemo(
    () => computeDeviceLastFaultTs(devices, state),
    [devices, state],
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
            <TableHead className="text-muted-foreground whitespace-nowrap">Last known fault</TableHead>
            {definitions.map((d) => (
              <TableHead key={d.fault_id} className="text-center font-medium">
                {d.name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {devices.map((dev) => (
            <TableRow key={deviceRowKey(dev)}>
              <TableCell className="font-mono">{dev.bacnet_device_id}</TableCell>
              <TableCell>{dev.equipment_name}</TableCell>
              {siteMap && (
                <TableCell className="text-muted-foreground">
                  {siteMap.get(dev.site_id)?.name ?? dev.site_name}
                </TableCell>
              )}
              <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                {lastFaultByDevice.get(deviceRowKey(dev))
                  ? timeAgo(lastFaultByDevice.get(deviceRowKey(dev))!)
                  : "—"}
              </TableCell>
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

const ROW_LIMIT_OPTIONS = [25, 50, 100] as const;
const DEFAULT_ROW_LIMIT = 50;

function FaultDataPreviewSection({
  siteId,
  startDate,
  endDate,
}: {
  siteId: string | undefined;
  startDate: string;
  endDate: string;
}) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [rowLimit, setRowLimit] = useState(DEFAULT_ROW_LIMIT);

  const { data: seriesData, isLoading: seriesLoading } = useFaultResultsSeries(
    siteId,
    startDate,
    endDate,
  );
  const series = seriesData?.series ?? [];
  const effectiveIndex =
    series.length === 0 ? 0 : Math.min(selectedIndex, series.length - 1);
  const selected = series[effectiveIndex] ?? null;

  const { data: rawData, isLoading: rawLoading } = useFaultResultsRaw(
    selected?.fault_id ?? "",
    selected?.site_id,
    selected?.equipment_id,
    rowLimit,
  );
  const rows = rawData?.rows ?? [];

  return (
    <details className="group mb-8 rounded-xl border border-border/80 bg-muted/30">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
        <span className="inline-flex items-center gap-2">
          Fault calculation data preview
          <span className="text-xs font-normal">
            (last N rows of fault_results per fault × device)
          </span>
        </span>
      </summary>
      <div className="border-t border-border/80 px-4 pb-4 pt-3">
        {seriesLoading ? (
          <Skeleton className="h-32 w-full rounded-lg" />
        ) : series.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No fault result data in the selected time range. Run FDD and ensure fault_results exist.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">View data for</span>
                <select
                  value={effectiveIndex}
                  onChange={(e) => setSelectedIndex(Number(e.target.value))}
                  className="rounded-md border border-input bg-background px-2 py-1.5 text-sm font-medium"
                >
                  {series.map((s, i) => (
                    <option key={`${s.fault_id}-${s.site_id}-${s.equipment_id}`} value={i}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Rows to show</span>
                <select
                  value={rowLimit}
                  onChange={(e) => setRowLimit(Number(e.target.value))}
                  className="rounded-md border border-input bg-background px-2 py-1.5 text-sm tabular-nums"
                >
                  {ROW_LIMIT_OPTIONS.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {rawLoading ? (
              <Skeleton className="h-64 w-full rounded-lg" />
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border bg-background shadow-sm">
                <table
                  className="w-full min-w-[640px] border-collapse text-sm"
                  data-testid="fault-data-preview-table"
                >
                  <thead>
                    <tr className="border-b border-border bg-muted/60">
                      <th className="sticky left-0 z-10 min-w-[180px] border-r border-border bg-muted/60 px-3 py-2 text-left font-semibold">
                        Timestamp
                      </th>
                      <th className="min-w-[100px] border-r border-border px-3 py-2 text-left font-semibold">
                        Site
                      </th>
                      <th className="min-w-[120px] border-r border-border px-3 py-2 text-left font-semibold">
                        Equipment
                      </th>
                      <th className="min-w-[120px] border-r border-border px-3 py-2 text-left font-semibold">
                        Fault ID
                      </th>
                      <th className="min-w-[80px] border-r border-border px-3 py-2 text-right font-semibold tabular-nums">
                        Flag
                      </th>
                      <th className="min-w-[140px] px-3 py-2 text-left font-semibold">
                        Evidence
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr
                        key={`${r.ts}-${i}`}
                        className={`border-b border-border/60 ${
                          i % 2 === 0 ? "bg-background" : "bg-muted/20"
                        }`}
                      >
                        <td className="sticky left-0 z-10 border-r border-border/60 bg-inherit px-3 py-1.5 font-mono text-xs tabular-nums">
                          {r.ts}
                        </td>
                        <td className="border-r border-border/60 px-3 py-1.5 font-mono text-xs">
                          {r.site_id}
                        </td>
                        <td className="border-r border-border/60 px-3 py-1.5 font-mono text-xs">
                          {r.equipment_id}
                        </td>
                        <td className="border-r border-border/60 px-3 py-1.5 font-mono text-xs">
                          {r.fault_id}
                        </td>
                        <td className="border-r border-border/60 px-3 py-1.5 text-right font-mono tabular-nums">
                          {r.flag_value}
                        </td>
                        <td className="max-w-[min(28rem,40vw)] align-top px-3 py-1.5 text-muted-foreground">
                          <FaultEvidenceCell evidence={r.evidence} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rows.length === 0 && !rawLoading && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    No rows for this selection.
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </details>
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

function FaultEvidenceCell({ evidence }: { evidence: unknown }) {
  if (evidence == null) return "—";
  if (typeof evidence === "string") {
    return <span className="break-all font-mono text-xs text-muted-foreground">{evidence}</span>;
  }
  return (
    <JsonPrettyPanel
      value={evidence}
      maxHeightClass="max-h-40"
      compact
      showCopy={false}
      defaultExpandDepth={1}
    />
  );
}

function RuleFileContentPreview({ content }: { content: string }) {
  const t = content.trim();
  let parsedJson: unknown | null = null;
  if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
    try {
      parsedJson = JSON.parse(t) as unknown;
    } catch {
      parsedJson = null;
    }
  }
  if (parsedJson !== null) {
    return <JsonPrettyPanel value={parsedJson} maxHeightClass="max-h-96" defaultExpandDepth={2} />;
  }
  return (
    <pre className="max-h-96 overflow-auto rounded-md border border-border/60 bg-muted/50 p-3 font-mono text-xs whitespace-pre-wrap break-all text-foreground">
      {content}
    </pre>
  );
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
  const queryClient = useQueryClient();
  const { data, isLoading } = useRulesList();
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploadFilename, setUploadFilename] = useState("");
  const [uploadContent, setUploadContent] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);

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

  const uploadMutation = useMutation({
    mutationFn: () => uploadRule(uploadFilename.trim() || "rule.yaml", uploadContent),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
      setUploadFilename("");
      setUploadContent("");
      setUploadError(null);
      if (data?.filename) openFile(data.filename);
    },
    onError: (e: Error) => setUploadError(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (filename: string) => deleteRule(filename),
    onSuccess: (_, filename) => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
      if (selectedFile === filename) {
        setSelectedFile(null);
        setFileContent(null);
      }
    },
  });

  const syncMutation = useMutation({
    mutationFn: syncRuleDefinitions,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["faults"] }),
  });

  const handleUpload = (e: React.FormEvent) => {
    e.preventDefault();
    setUploadError(null);
    const fn = uploadFilename.trim();
    if (!fn.endsWith(".yaml")) {
      setUploadError("Filename must end with .yaml");
      return;
    }
    uploadMutation.mutate();
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const name = file.name.endsWith(".yaml") ? file.name : `${file.name}.yaml`;
    setUploadFilename(name);
    const reader = new FileReader();
    reader.onload = () => setUploadContent(String(reader.result ?? ""));
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleDownload = useCallback((filename: string) => {
    apiFetchText(`/rules/${encodeURIComponent(filename)}`)
      .then((text) => {
        const blob = new Blob([text], { type: "application/x-yaml" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((err: Error) => setFileError(err.message));
  }, []);

  const handleDelete = (filename: string) => {
    if (!window.confirm(`Remove rule file "${filename}"? Definition will be removed after next FDD run or Sync.`)) return;
    deleteMutation.mutate(filename);
  };

  if (isLoading) return <Skeleton className="h-40 w-full rounded-xl" />;
  const files = data?.files ?? [];
  const primaryRuleFiles = files.filter((f) => !isHotReloadBenchArtifact(f));
  const benchArtifactFiles = files.filter((f) => isHotReloadBenchArtifact(f));
  const rulesDir = data?.rules_dir ?? "";

  return (
    <div className="mb-8">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">
        FDD rule files (YAML)
      </h2>
      <p className="mb-2 text-xs text-muted-foreground">
        Rule YAML from platform config (rules_dir via GET /config). Upload, download, or delete files; FDD loop hot-reloads each run.
        Timestamped <span className="font-mono">test_*_*</span> files are bench/E2E artifacts, not created by site bootstrap—delete them if you do not need them.
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

          {/* Upload */}
          <form onSubmit={handleUpload} className="mb-4 space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <input
                type="text"
                placeholder="filename.yaml"
                value={uploadFilename}
                onChange={(e) => setUploadFilename(e.target.value)}
                className="rounded-md border border-input bg-background px-3 py-1.5 font-mono text-sm"
              />
              <label className="cursor-pointer">
                <span className="inline-flex items-center rounded-md border border-input bg-muted px-3 py-1.5 text-sm hover:bg-muted/80">Choose file</span>
                <input type="file" accept=".yaml,.yml" className="sr-only" onChange={handleFileSelect} />
              </label>
              <button
                type="submit"
                disabled={uploadMutation.isPending || !uploadContent.trim()}
                className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-muted"
              >
                {uploadMutation.isPending ? "Uploading…" : "Upload"}
              </button>
              <button
                type="button"
                onClick={() => syncMutation.mutate()}
                disabled={syncMutation.isPending}
                className="rounded-md border border-input bg-muted/50 px-3 py-1.5 text-sm hover:bg-muted"
              >
                {syncMutation.isPending ? "Syncing…" : "Sync definitions"}
              </button>
            </div>
            <textarea
              placeholder="Paste YAML or use Choose file…"
              value={uploadContent}
              onChange={(e) => setUploadContent(e.target.value)}
              rows={6}
              className="w-full rounded-md border border-input bg-muted/30 p-2 font-mono text-xs"
            />
            {uploadError && <p className="text-sm text-destructive">{uploadError}</p>}
          </form>

          {files.length === 0 && !data?.error ? (
            <p className="text-sm text-muted-foreground">No .yaml files in rules_dir.</p>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {primaryRuleFiles.map((name) => (
                  <span key={name} className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2 py-1">
                    <button
                      type="button"
                      onClick={() => openFile(name)}
                      className={`font-mono text-sm transition-colors ${
                        selectedFile === name ? "text-primary underline" : "hover:text-primary"
                      }`}
                    >
                      {name}
                    </button>
                    <button type="button" className="h-6 px-1 text-xs hover:text-primary" onClick={() => handleDownload(name)} title="Download">
                      ↓
                    </button>
                    <button type="button" className="h-6 px-1 text-xs text-destructive hover:text-destructive" onClick={() => handleDelete(name)} title="Delete">
                      ×
                    </button>
                  </span>
                ))}
              </div>
              {benchArtifactFiles.length > 0 && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                  <p className="mb-2 text-xs font-medium text-amber-800 dark:text-amber-200">
                    Bench / E2E rule copies ({benchArtifactFiles.length})
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {benchArtifactFiles.map((name) => (
                      <span key={name} className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2 py-1">
                        <button
                          type="button"
                          onClick={() => openFile(name)}
                          className={`font-mono text-sm transition-colors ${
                            selectedFile === name ? "text-primary underline" : "hover:text-primary"
                          }`}
                        >
                          {name}
                        </button>
                        <button type="button" className="h-6 px-1 text-xs hover:text-primary" onClick={() => handleDownload(name)} title="Download">
                          ↓
                        </button>
                        <button type="button" className="h-6 px-1 text-xs text-destructive hover:text-destructive" onClick={() => handleDelete(name)} title="Delete">
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
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
                <RuleFileContentPreview content={fileContent} />
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

      <FaultDataPreviewSection
        siteId={selectedSiteId ?? undefined}
        startDate={start.slice(0, 10)}
        endDate={end.slice(0, 10)}
      />

      <FaultDefinitionsSection />
      <RuleFilesSection />

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Active fault rows (current state)</h2>
        {selectedSiteId ? <SiteFaultsView siteId={selectedSiteId} /> : <AllFaultsView />}
      </section>
    </div>
  );
}
