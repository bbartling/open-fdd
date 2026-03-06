import { useState, useCallback, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Check, Play, Database, Upload, Code, Server, Save, RotateCcw, Search, Trash2, Plus, Building2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSiteContext } from "@/contexts/site-context";
import { useAllEquipment, useAllPoints, useEquipment, usePoints, useSites } from "@/hooks/use-sites";
import { useActiveFaults, useSiteFaults } from "@/hooks/use-faults";
import { EquipmentTable } from "@/components/site/EquipmentTable";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import {
  createSite,
  deleteSite,
  dataModelSerialize,
  dataModelReset,
  dataModelCheck,
  type SiteCreate,
} from "@/lib/crud-api";
import type {
  DataModelExportRow,
  DataModelImportBody,
  DataModelImportResponse,
  SparqlResponse,
} from "@/types/api";

const DEFAULT_SPARQL = `PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  ?site rdfs:label ?site_label
}`;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);
  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
      {copied ? "Copied" : "Copy for AI"}
    </button>
  );
}

export function DataModelPage() {
  const queryClient = useQueryClient();
  const { selectedSiteId } = useSiteContext();
  const [importJson, setImportJson] = useState("");
  const [importResult, setImportResult] = useState<DataModelImportResponse | null>(null);
  const [sparqlQuery, setSparqlQuery] = useState(DEFAULT_SPARQL);
  const [sparqlError, setSparqlError] = useState<string | null>(null);
  const [newSiteName, setNewSiteName] = useState("");
  const [newSiteDescription, setNewSiteDescription] = useState("");
  const [checkResult, setCheckResult] = useState<Record<string, unknown> | null>(null);
  const [resetConfirm, setResetConfirm] = useState("");
  const [deleteAllConfirm, setDeleteAllConfirm] = useState("");

  const { data: equipmentAll = [], isLoading: equipmentAllLoading } = useAllEquipment();
  const { data: equipmentSite = [], isLoading: equipmentSiteLoading } = useEquipment(selectedSiteId ?? undefined);
  const { data: pointsAll = [] } = useAllPoints();
  const { data: pointsSite = [] } = usePoints(selectedSiteId ?? undefined);
  const { data: faultsAll = [] } = useActiveFaults();
  const { data: faultsSite = [] } = useSiteFaults(selectedSiteId ?? undefined);
  const { data: sites = [] } = useSites();

  const equipment = selectedSiteId ? equipmentSite : equipmentAll;
  const points = selectedSiteId ? pointsSite : pointsAll;
  const faults = selectedSiteId ? faultsSite : faultsAll;
  const equipmentLoading = selectedSiteId ? equipmentSiteLoading : equipmentAllLoading;
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);

  const { data: exportData, isLoading: exportLoading } = useQuery<DataModelExportRow[]>({
    queryKey: ["data-model", "export"],
    queryFn: () => apiFetch<DataModelExportRow[]>("/data-model/export"),
    staleTime: 60 * 1000,
  });

  const sparqlMutation = useMutation({
    mutationFn: (query: string) =>
      apiFetch<SparqlResponse>("/data-model/sparql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      }),
    onSuccess: () => setSparqlError(null),
    onError: (err: Error) => setSparqlError(err.message),
  });

  const importMutation = useMutation({
    mutationFn: (body: DataModelImportBody) =>
      apiFetch<DataModelImportResponse>("/data-model/import", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      setImportResult(data);
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
    },
    onError: (err: Error) => setImportResult({ total: 0, warnings: [err.message] }),
  });

  const serializeMutation = useMutation({
    mutationFn: dataModelSerialize,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });

  const resetMutation = useMutation({
    mutationFn: dataModelReset,
    onSuccess: () => {
      setResetConfirm("");
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
    },
  });

  const checkMutation = useMutation({
    mutationFn: dataModelCheck,
    onSuccess: (data) => setCheckResult(data ?? null),
  });

  const createSiteMutation = useMutation({
    mutationFn: (body: SiteCreate) => createSite(body),
    onSuccess: () => {
      setNewSiteName("");
      setNewSiteDescription("");
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });

  const deleteSiteMutation = useMutation({
    mutationFn: (siteId: string) => deleteSite(siteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
    },
  });

  const exportJson = exportData == null ? "" : JSON.stringify(exportData, null, 2);
  const sparqlBindings = sparqlMutation.data?.bindings ?? [];

  const handleImport = () => {
    try {
      const parsed = JSON.parse(importJson) as DataModelImportBody | DataModelExportRow[];
      const body: DataModelImportBody = Array.isArray(parsed) ? { points: parsed } : parsed;
      if (!body.points?.length) {
        setImportResult({ total: 0, warnings: ["No points in payload"] });
        return;
      }
      importMutation.mutate(body);
    } catch (e) {
      setImportResult({ total: 0, warnings: [e instanceof Error ? e.message : "Invalid JSON"] });
    }
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Data model</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Export the data model as JSON for AI tagging, paste tagged JSON back to import, and run
        SPARQL queries against the Brick + BACnet graph.
      </p>

      <div className="space-y-8">
        {/* Sites */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Building2 className="h-5 w-5" />
              Sites
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Create and delete sites. Deleting a site cascades to equipment, points, timeseries, and faults. Same as
              script <code className="rounded bg-muted px-1">delete_all_sites_and_reset.py</code> when you delete all.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Name</label>
                <input
                  type="text"
                  value={newSiteName}
                  onChange={(e) => setNewSiteName(e.target.value)}
                  placeholder="Site name"
                  className="h-9 w-48 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Description (optional)</label>
                <input
                  type="text"
                  value={newSiteDescription}
                  onChange={(e) => setNewSiteDescription(e.target.value)}
                  placeholder="Optional"
                  className="h-9 w-48 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <button
                type="button"
                onClick={() => {
                  if (!newSiteName.trim()) return;
                  createSiteMutation.mutate({ name: newSiteName.trim(), description: newSiteDescription.trim() || null });
                }}
                disabled={createSiteMutation.isPending || !newSiteName.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
                Add site
              </button>
            </div>
            {createSiteMutation.isError && (
              <p className="text-sm text-destructive">{createSiteMutation.error?.message}</p>
            )}
            <div className="overflow-x-auto rounded-lg border border-border/60">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="w-[100px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sites.map((site) => (
                    <TableRow key={site.id}>
                      <TableCell className="font-medium">{site.name}</TableCell>
                      <TableCell className="text-muted-foreground">{site.description ?? "—"}</TableCell>
                      <TableCell>
                        <button
                          type="button"
                          onClick={() => {
                            if (window.confirm(`Delete site "${site.name}"? This removes all equipment, points, timeseries, and faults for this site.`)) {
                              deleteSiteMutation.mutate(site.id);
                            }
                          }}
                          disabled={deleteSiteMutation.isPending}
                          className="inline-flex items-center gap-1 rounded border border-border/60 px-2 py-1 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
                        >
                          <Trash2 className="h-3 w-3" />
                          Delete
                        </button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {sites.length === 0 && <p className="text-sm text-muted-foreground">No sites. Add one above.</p>}
            {sites.length > 0 && (
              <div className="border-t border-border/60 pt-4">
                <p className="mb-2 text-sm font-medium text-muted-foreground">Delete all sites (like delete_all_sites_and_reset.py)</p>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={deleteAllConfirm}
                    onChange={(e) => setDeleteAllConfirm(e.target.value)}
                    placeholder={`Type ${sites.length} to confirm`}
                    className="h-9 w-40 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                    <button
                    type="button"
                    onClick={async () => {
                      if (deleteAllConfirm !== String(sites.length)) {
                        alert(`Type ${sites.length} in the box to confirm.`);
                        return;
                      }
                      try {
                        for (const s of sites) {
                          await deleteSite(s.id);
                        }
                        await dataModelReset();
                        setDeleteAllConfirm("");
                        queryClient.invalidateQueries({ queryKey: ["sites"] });
                        queryClient.invalidateQueries({ queryKey: ["data-model"] });
                        queryClient.invalidateQueries({ queryKey: ["equipment"] });
                        queryClient.invalidateQueries({ queryKey: ["points"] });
                        queryClient.invalidateQueries({ queryKey: ["faults"] });
                      } catch (err) {
                        alert(err instanceof Error ? err.message : "Delete all failed");
                      }
                    }}
                    disabled={deleteAllConfirm !== String(sites.length)}
                    className="inline-flex items-center gap-2 rounded-lg border border-destructive/60 bg-destructive/10 px-4 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/20 disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete all sites and reset graph
                  </button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Export */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Database className="h-5 w-5" />
              Export (for AI / copy-paste)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              GET /data-model/export — BACnet discovery + DB points. Copy and paste into your LLM
              for Brick tagging, then re-import below.
            </p>
            {exportLoading && <Skeleton className="h-48 w-full rounded-lg" />}
            {!exportLoading && exportJson && (
              <div className="flex flex-col gap-2">
                <pre className="max-h-80 overflow-auto rounded-lg border border-border/60 bg-muted/30 p-4 text-xs font-mono">
                  {exportJson.slice(0, 2000)}
                  {exportJson.length > 2000 ? "\n… (truncated; use Copy for full JSON)" : ""}
                </pre>
                <CopyButton text={exportJson} />
              </div>
            )}
            {!exportLoading && (!exportData || exportData.length === 0) && (
              <p className="text-sm text-muted-foreground">No points in the data model yet.</p>
            )}
          </CardContent>
        </Card>

        {/* Equipment */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Server className="h-5 w-5" />
              Equipment
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-4 text-sm text-muted-foreground">
              Equipment in the data model. Filter by site using the site selector in the top bar.
            </p>
            {equipmentLoading && <Skeleton className="h-72 w-full rounded-lg" />}
            {!equipmentLoading && (
              <EquipmentTable
                equipment={equipment}
                points={points}
                faults={faults}
                siteMap={selectedSiteId ? undefined : siteMap}
              />
            )}
          </CardContent>
        </Card>

        {/* Import */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Upload className="h-5 w-5" />
              Import (paste from AI)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Paste JSON (array of points or <code className="rounded bg-muted px-1">{"{ points: [...] }"}</code>)
              and click Import to update the data model. Same as PUT /data-model/import.
            </p>
            <textarea
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
              placeholder='[{"point_id": "...", "brick_type": "Supply_Air_Temperature_Sensor", ...}] or { "points": [...] }'
              className="h-40 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              spellCheck={false}
            />
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleImport}
                disabled={importMutation.isPending || !importJson.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                Import
              </button>
              {importResult != null && (
                <span className="text-sm text-muted-foreground">
                  {importResult.created != null && `Created: ${importResult.created}`}
                  {importResult.updated != null && ` Updated: ${importResult.updated}`}
                  {importResult.total != null && ` Total: ${importResult.total}`}
                  {importResult.warnings?.length ? ` — ${importResult.warnings.join("; ")}` : ""}
                </span>
              )}
            </div>
          </CardContent>
        </Card>

        {/* SPARQL */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Code className="h-5 w-5" />
              SPARQL (query the data model)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Run a SPARQL query against the current Brick + BACnet graph. Results appear below.
            </p>
            <textarea
              value={sparqlQuery}
              onChange={(e) => setSparqlQuery(e.target.value)}
              className="h-40 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              spellCheck={false}
            />
            <button
              type="button"
              onClick={() => sparqlMutation.mutate(sparqlQuery)}
              disabled={sparqlMutation.isPending || !sparqlQuery.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              <Play className="h-4 w-4" />
              Run SPARQL
            </button>
            {sparqlError && (
              <p className="text-sm text-destructive">{sparqlError}</p>
            )}
            {sparqlBindings.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-border/60">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {Object.keys(sparqlBindings[0]).map((key) => (
                        <TableHead key={key} className="font-mono text-xs">
                          {key}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sparqlBindings.map((row, i) => (
                      <TableRow key={i}>
                        {Object.values(row).map((val, j) => (
                          <TableCell key={j} className="font-mono text-xs">
                            {val ?? "—"}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {sparqlMutation.isSuccess && sparqlBindings.length === 0 && (
              <p className="text-sm text-muted-foreground">No bindings (empty result).</p>
            )}
          </CardContent>
        </Card>

        {/* Graph actions */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <RotateCcw className="h-5 w-5" />
              Graph actions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Serialize in-memory graph to TTL file; reset graph to DB-only (clears BACnet); run integrity check.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => serializeMutation.mutate()}
                disabled={serializeMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
              >
                <Save className="h-4 w-4" />
                {serializeMutation.isPending ? "Serializing…" : "Serialize to TTL"}
              </button>
              <button
                type="button"
                onClick={() => checkMutation.mutate()}
                disabled={checkMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
              >
                <Search className="h-4 w-4" />
                {checkMutation.isPending ? "Checking…" : "Check integrity"}
              </button>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={resetConfirm}
                  onChange={(e) => setResetConfirm(e.target.value)}
                  placeholder="Type reset to confirm"
                  className="h-9 w-40 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (resetConfirm.trim().toLowerCase() !== "reset") {
                      alert('Type "reset" to confirm.');
                      return;
                    }
                    resetMutation.mutate();
                  }}
                  disabled={resetMutation.isPending || resetConfirm.trim().toLowerCase() !== "reset"}
                  className="inline-flex items-center gap-2 rounded-lg border border-amber-600/60 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-700 transition-colors hover:bg-amber-500/20 disabled:opacity-50 dark:text-amber-400"
                >
                  <RotateCcw className="h-4 w-4" />
                  Reset graph to DB-only
                </button>
              </div>
            </div>
            {serializeMutation.isSuccess && (
              <p className="text-sm text-muted-foreground">
                Serialized to {String((serializeMutation.data as { path?: string })?.path ?? "—")}
              </p>
            )}
            {checkResult != null && (
              <pre className="max-h-40 overflow-auto rounded-lg border border-border/60 bg-muted/30 p-3 text-xs">
                {JSON.stringify(checkResult, null, 2)}
              </pre>
            )}
            {resetMutation.isSuccess && (
              <p className="text-sm text-muted-foreground">
                {(resetMutation.data as { message?: string })?.message ?? "Graph reset."}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
