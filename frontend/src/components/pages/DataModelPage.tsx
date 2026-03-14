import { useState, useCallback, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, Database, Upload, Code, Server, Save, RotateCcw, Search, Trash2, Plus, Building2, Download, FileText, FileUp, Sparkles, Eye, EyeOff } from "lucide-react";
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
import { apiFetch, apiFetchText } from "@/lib/api";
import {
  createSite,
  deleteSite,
  dataModelSerialize,
  dataModelReset,
  dataModelCheck,
  tagPointsWithOpenAi,
  type SiteCreate,
  type DataModelCheckResponse,
} from "@/lib/crud-api";
import type {
  DataModelExportRow,
  DataModelImportBody,
  DataModelImportResponse,
  SparqlResponse,
  TagWithOpenAiRequest,
  TagWithOpenAiResponse,
} from "@/types/api";

const DEFAULT_SPARQL = `PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  ?site rdfs:label ?site_label
}`;

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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
  const [checkResult, setCheckResult] = useState<DataModelCheckResponse | null>(null);
  const [resetConfirm, setResetConfirm] = useState("");
  const [deleteAllConfirm, setDeleteAllConfirm] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [ttlError, setTtlError] = useState<string | null>(null);
  const [showExportPreview, setShowExportPreview] = useState(false);
  const importFileInputRef = useRef<HTMLInputElement>(null);
  const sparqlFileInputRef = useRef<HTMLInputElement>(null);

  // AI tagging state — key loaded from localStorage if user previously enabled remember
  const [openAiKey, setOpenAiKey] = useState<string>(() => {
    try { return localStorage.getItem("openFddOpenAiKey") ?? ""; } catch { return ""; }
  });
  const [rememberKey, setRememberKey] = useState<boolean>(() => {
    try { return localStorage.getItem("openFddRememberKey") === "true"; } catch { return false; }
  });
  const [openAiModel, setOpenAiModel] = useState("gpt-4o");
  const [showAiKey, setShowAiKey] = useState(false);
  const [autoImportAiTag, setAutoImportAiTag] = useState(false);
  const [tagSelectedSiteOnly, setTagSelectedSiteOnly] = useState(false);
  const [aiTagResult, setAiTagResult] = useState<TagWithOpenAiResponse | null>(null);
  const [aiTagError, setAiTagError] = useState<string | null>(null);

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

  const sparqlMutation = useMutation<SparqlResponse, Error, string>({
    mutationFn: (query) =>
      apiFetch<SparqlResponse>("/data-model/sparql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      }),
    onSuccess: () => setSparqlError(null),
    onError: (err: Error) => setSparqlError(err.message),
  });

  const importMutation = useMutation<DataModelImportResponse, Error, DataModelImportBody>({
    mutationFn: (body) =>
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
    onSuccess: (data: DataModelCheckResponse | undefined) => setCheckResult(data ?? null),
  });

  const tagWithAiMutation = useMutation<TagWithOpenAiResponse, Error, TagWithOpenAiRequest>({
    mutationFn: tagPointsWithOpenAi,
    onSuccess: (data) => {
      setAiTagResult(data);
      setAiTagError(null);
      // Pre-fill import textarea so user can review the exact tagged payload.
      const payload = { points: data.points, equipment: data.equipment };
      setImportJson(JSON.stringify(payload, null, 2));

      if (data.meta.import_result) {
        setImportResult(data.meta.import_result);
        queryClient.invalidateQueries({ queryKey: ["data-model"] });
        queryClient.invalidateQueries({ queryKey: ["sites"] });
        queryClient.invalidateQueries({ queryKey: ["equipment"] });
        queryClient.invalidateQueries({ queryKey: ["points"] });
        queryClient.invalidateQueries({ queryKey: ["faults"] });
      }
    },
    onError: (err) => {
      setAiTagError(err.message);
      setAiTagResult(null);
    },
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
  const sparqlBindings: Record<string, string | null>[] = sparqlMutation.data?.bindings ?? [];
  // Union of all keys so optional SPARQL vars (e.g. ?rule_input) show as a column even if first row lacks it
  const sparqlColumns =
    sparqlBindings.length > 0
      ? Array.from(new Set(sparqlBindings.flatMap((r) => Object.keys(r)))).sort()
      : [];

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

  const handleTagWithAi = () => {
    if (!openAiKey.trim()) return;
    if (rememberKey) {
      try {
        localStorage.setItem("openFddOpenAiKey", openAiKey);
        localStorage.setItem("openFddRememberKey", "true");
      } catch { /* storage unavailable */ }
    } else {
      try {
        localStorage.removeItem("openFddOpenAiKey");
        localStorage.removeItem("openFddRememberKey");
      } catch { /* storage unavailable */ }
    }
    setAiTagError(null);
    setAiTagResult(null);
    tagWithAiMutation.mutate({
      // Match manual workflow by default (all sites). Users can opt into selected-site-only.
      site_id: tagSelectedSiteOnly ? (selectedSiteId ?? null) : null,
      openai_api_key: openAiKey,
      model: openAiModel,
      auto_import: autoImportAiTag,
    });
  };

  const handleViewTtl = useCallback(async () => {
    setTtlError(null);
    setTtlLoading(true);
    try {
      const ttl = await apiFetchText("/data-model/ttl?save=true", {
        headers: { Accept: "text/plain" },
      });
      const escaped = ttl
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      const w = window.open("", "_blank");
      if (w) {
        w.document.write(
          `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head><body><pre style="margin:0;padding:1rem;font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap;word-break:break-all;">${escaped}</pre></body></html>`
        );
        w.document.close();
      } else {
        setTtlError("Popup blocked. Allow popups for this site and try again.");
      }
    } catch (err) {
      setTtlError(err instanceof Error ? err.message : "Failed to load TTL");
    } finally {
      setTtlLoading(false);
    }
  }, []);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Data model</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Export the data model as JSON for AI tagging, paste tagged JSON back to import, and run
        SPARQL queries against the Brick + BACnet graph.
      </p>

      <div className="space-y-8">
        {/* Graph actions */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <RotateCcw className="h-5 w-5" />
              Graph actions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {sites.length > 0 && (
              <div className="rounded-lg border border-border/60 p-4">
                <p className="mb-2 text-sm font-medium text-muted-foreground">Remove all sites from data model</p>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={deleteAllConfirm}
                    onChange={(e) => setDeleteAllConfirm(e.target.value)}
                    placeholder={`Type ${sites.length} to confirm`}
                    className="h-9 w-40 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    data-testid="delete-all-confirm-input"
                  />
                  <button
                    type="button"
                    data-testid="delete-all-and-reset-button"
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
                        alert(err instanceof Error ? err.message : "Remove all failed");
                      }
                    }}
                    disabled={deleteAllConfirm !== String(sites.length)}
                    className="inline-flex items-center gap-2 rounded-lg border border-destructive/60 bg-destructive/10 px-4 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/20 disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" />
                    Remove all sites and reset graph
                  </button>
                </div>
              </div>
            )}
            <p className="text-sm text-muted-foreground">
              Serialize in-memory graph to TTL file; reset graph to DB-only (clears BACnet); run integrity check.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleViewTtl}
                disabled={ttlLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
                title="Open full Brick + BACnet TTL in a new tab (raw text)"
              >
                <FileText className="h-4 w-4" />
                {ttlLoading ? "Loading…" : "View full data model (TTL)"}
              </button>
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
            {ttlError && (
              <p className="text-sm text-destructive">{ttlError}</p>
            )}
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
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => exportData && downloadJson(exportData, "data-model-export.json")}
                    className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted self-start"
                    title="Download full export as JSON file"
                  >
                    <Download className="h-4 w-4" />
                    Download JSON
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowExportPreview((v) => !v)}
                    className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-muted self-start"
                  >
                    <FileText className="h-4 w-4" />
                    {showExportPreview ? "Hide preview" : "Show preview"}
                  </button>
                </div>
                {showExportPreview && (
                  <pre className="max-h-80 overflow-auto rounded-lg border border-border/60 bg-muted/30 p-4 text-xs font-mono">
                    {exportJson.slice(0, 2000)}
                    {exportJson.length > 2000 ? "\n… (truncated; download for full)" : ""}
                  </pre>
                )}
              </div>
            )}
            {!exportLoading && (!exportData || exportData.length === 0) && (
              <p className="text-sm text-muted-foreground">No points in the data model yet.</p>
            )}
          </CardContent>
        </Card>

        {/* AI Tagging */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-5 w-5" />
              AI Tagging (OpenAI)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Automatically tag BACnet points with Brick types, rule inputs, and equipment using
              OpenAI. Enter your API key below and click <strong>Tag with AI</strong> — the tagged
              JSON will be pre-filled in the Import section below for review before you commit it.
            </p>
            <p className="text-xs text-muted-foreground">
              <strong>No API key?</strong> Use the manual method: export the JSON above, paste it
              into ChatGPT with the canonical prompt from the README, then paste the result into the
              Import section below.
            </p>

            {/* API key input */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-muted-foreground">
                OpenAI API key
              </label>
              <div className="flex items-center gap-2">
                <input
                  type={showAiKey ? "text" : "password"}
                  value={openAiKey}
                  onChange={(e) => setOpenAiKey(e.target.value)}
                  placeholder="sk-..."
                  autoComplete="off"
                  className="h-9 flex-1 rounded-lg border border-border/60 bg-background px-3 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  data-testid="ai-tag-api-key-input"
                />
                <button
                  type="button"
                  onClick={() => setShowAiKey((v) => !v)}
                  className="inline-flex items-center rounded-lg border border-border/60 bg-muted/50 p-2 text-muted-foreground transition-colors hover:bg-muted"
                  title={showAiKey ? "Hide key" : "Show key"}
                >
                  {showAiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setOpenAiKey("");
                    setRememberKey(false);
                    try {
                      localStorage.removeItem("openFddOpenAiKey");
                      localStorage.removeItem("openFddRememberKey");
                    } catch { /* storage unavailable */ }
                  }}
                  className="inline-flex items-center rounded-lg border border-border/60 bg-muted/50 px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted"
                  title="Clear stored key"
                >
                  Clear
                </button>
              </div>
            </div>

            {/* Model selector */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-muted-foreground">Model</label>
              <select
                value={openAiModel}
                onChange={(e) => setOpenAiModel(e.target.value)}
                className="h-9 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="gpt-4o">gpt-4o</option>
                <option value="gpt-4o-mini">gpt-4o-mini</option>
                <option value="gpt-4-turbo">gpt-4-turbo</option>
              </select>
            </div>

            {/* Remember key toggle */}
            <div className="space-y-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={rememberKey}
                  onChange={(e) => setRememberKey(e.target.checked)}
                  className="h-4 w-4 rounded border-border/60"
                  data-testid="ai-tag-remember-key"
                />
                Remember key in this browser
              </label>
              {rememberKey && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  ⚠ The key will be saved in this browser&apos;s localStorage. Anyone with access
                  to this browser profile or device can read it. Only enable this on a private,
                  trusted device.
                </p>
              )}
            </div>

            {/* Auto import toggle */}
            <div className="space-y-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={autoImportAiTag}
                  onChange={(e) => setAutoImportAiTag(e.target.checked)}
                  className="h-4 w-4 rounded border-border/60"
                  data-testid="ai-tag-auto-import"
                />
                Automatically import tagged result
              </label>
              <p className="text-xs text-muted-foreground">
                When enabled, the tagged payload is immediately applied to the data model after validation.
              </p>
            </div>

            {/* Scope toggle */}
            <div className="space-y-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={tagSelectedSiteOnly}
                  onChange={(e) => setTagSelectedSiteOnly(e.target.checked)}
                  className="h-4 w-4 rounded border-border/60"
                  data-testid="ai-tag-selected-site-only"
                />
                Tag selected site only
              </label>
              <p className="text-xs text-muted-foreground">
                Off (default): tags points from all sites, matching the Export panel above. On: only tags the currently selected site.
              </p>
            </div>

            {/* Tag button */}
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleTagWithAi}
                disabled={!openAiKey.trim() || tagWithAiMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                data-testid="ai-tag-button"
              >
                <Sparkles className="h-4 w-4" />
                {tagWithAiMutation.isPending ? "Tagging…" : "Tag with AI"}
              </button>
              {tagWithAiMutation.isPending && (
                <span className="text-xs text-muted-foreground">
                  Calling OpenAI — this may take several minutes for large sites…
                </span>
              )}
            </div>

            {/* Result summary */}
            {aiTagResult && (
              <p className="text-sm text-muted-foreground" data-testid="ai-tag-result">
                Tagged {aiTagResult.meta.point_count} point
                {aiTagResult.meta.point_count !== 1 ? "s" : ""} and{" "}
                {aiTagResult.meta.equipment_count} equipment item
                {aiTagResult.meta.equipment_count !== 1 ? "s" : ""} using{" "}
                {aiTagResult.meta.model}
                {aiTagResult.meta.usage
                  ? ` (${aiTagResult.meta.usage.total_tokens} tokens)`
                  : ""}
                . {aiTagResult.meta.import_result
                  ? "Tagged payload was also imported into the data model."
                  : "Review the JSON in the Import section below, then click Import."}
              </p>
            )}
            {aiTagResult && aiTagResult.meta.point_count === 0 && (exportData?.length ?? 0) > 0 && (
              <p className="text-sm text-amber-600 dark:text-amber-400" data-testid="ai-tag-zero-points-hint">
                AI returned zero points even though export has data. If <strong>Tag selected site only</strong> is enabled,
                switch it off to tag all sites. If it is already off, rerun once and verify the API key/model are valid.
              </p>
            )}
            {aiTagError && (
              <p className="text-sm text-destructive" data-testid="ai-tag-error">
                {aiTagError}
              </p>
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
              or upload a JSON file, then click Import to update the data model. Same as PUT /data-model/import.
            </p>
            <input
              ref={importFileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                  try {
                    const text = String(reader.result ?? "");
                    JSON.parse(text);
                    setImportJson(text);
                  } catch {
                    setImportJson("");
                    alert("Invalid JSON in file. Check the file and try again.");
                  }
                  e.target.value = "";
                };
                reader.readAsText(file);
              }}
            />
            <textarea
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
              placeholder='[{"point_id": "...", "brick_type": "Supply_Air_Temperature_Sensor", ...}] or { "points": [...] }'
              className="h-40 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              spellCheck={false}
              data-testid="data-model-import-json"
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => importFileInputRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
                title="Load JSON from file into editor"
              >
                <FileUp className="h-4 w-4" />
                Upload JSON file
              </button>
              <button
                type="button"
                onClick={handleImport}
                disabled={importMutation.isPending || !importJson.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                data-testid="data-model-import-button"
              >
                <Upload className="h-4 w-4" />
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
              Run a SPARQL query against the current Brick + BACnet graph. Upload a .sparql file or type below. Results appear below.
            </p>
            <input
              ref={sparqlFileInputRef}
              type="file"
              accept=".sparql,text/plain"
              className="hidden"
              data-testid="sparql-file-input"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                  const text = typeof reader.result === "string" ? reader.result : "";
                  setSparqlQuery(text);
                };
                reader.readAsText(file);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              data-testid="sparql-upload-file-button"
              onClick={() => sparqlFileInputRef.current?.click()}
              className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-card px-4 py-2 text-sm font-medium transition-colors hover:bg-muted/80"
            >
              <FileUp className="h-4 w-4" />
              Upload .sparql file
            </button>
            <textarea
              data-testid="sparql-query-textarea"
              value={sparqlQuery}
              onChange={(e) => setSparqlQuery(e.target.value)}
              className="h-40 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              spellCheck={false}
            />
            <button
              type="button"
              data-testid="sparql-run-button"
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
            {sparqlBindings.length > 0 && sparqlColumns.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-border/60" data-testid="sparql-results-table">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {sparqlColumns.map((key) => (
                        <TableHead key={key} className="font-mono text-xs">
                          {key}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sparqlBindings.map((row: Record<string, string | null>, i: number) => (
                      <TableRow key={i}>
                        {sparqlColumns.map((key) => (
                          <TableCell key={key} className="font-mono text-xs">
                            {row[key] ?? "—"}
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
              Create and delete sites. Deleting a site cascades to equipment, points, timeseries, and faults.
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
                  data-testid="new-site-name-input"
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
                data-testid="add-site-button"
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
                    <TableRow key={site.id} data-site-id={site.id}>
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
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
