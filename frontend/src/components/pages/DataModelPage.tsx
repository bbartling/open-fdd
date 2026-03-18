import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ListOrdered, Database, Upload, Server, Save, RotateCcw, Search, Trash2, Plus, Building2, Download, FileText, FileUp, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSiteContext } from "@/contexts/site-context";
import { useAllEquipment, useAllPoints, useEquipment, usePoints, useSites } from "@/hooks/use-sites";
import { useActiveFaults, useSiteFaults } from "@/hooks/use-faults";
import { useCapabilities } from "@/hooks/use-fdd-status";
import { EquipmentTable } from "@/components/site/EquipmentTable";
import { BacnetDiscoveryPanel } from "@/components/site/BacnetDiscoveryPanel";
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
  TagWithOpenAiRequest,
  TagWithOpenAiResponse,
} from "@/types/api";
import { AI_MODEL_OPTIONS, DEFAULT_AI_MODEL } from "@/data/ai-models";

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
  const [importError, setImportError] = useState<string | null>(null);
  const [newSiteName, setNewSiteName] = useState("");
  const [newSiteDescription, setNewSiteDescription] = useState("");
  const [checkResult, setCheckResult] = useState<DataModelCheckResponse | null>(null);
  const [resetConfirm, setResetConfirm] = useState("");
  const [deleteAllConfirm, setDeleteAllConfirm] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [ttlError, setTtlError] = useState<string | null>(null);
  const [showAiAssist, setShowAiAssist] = useState(false);
  /** Chat prompt for in-house agent: describe HVAC and feeds/fed_by for tagging. */
  const [agentChatPrompt, setAgentChatPrompt] = useState(
    "Describe HVAC system and feeds or fed by relationships for AI to tag"
  );
  /** When true and multiple sites exist, only tag the site chosen in tagSiteId dropdown. */
  const [tagSpecificSite, setTagSpecificSite] = useState(false);
  /** Site to tag when tagSpecificSite is true (multiple sites). Ignored when only one site. */
  const [tagSiteId, setTagSiteId] = useState<string | null>(null);
  const [openAiModel, setOpenAiModel] = useState(DEFAULT_AI_MODEL);
  const [aiTagResult, setAiTagResult] = useState<TagWithOpenAiResponse | null>(null);
  const [aiTagError, setAiTagError] = useState<string | null>(null);
  const [aiTagStatus, setAiTagStatus] = useState<string>("");
  const [aiTagPhase, setAiTagPhase] = useState<"idle" | "running" | "success" | "error">("idle");
  const [aiMessages, setAiMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([]);

  const importFileInputRef = useRef<HTMLInputElement>(null);
  const { data: equipmentAll = [], isLoading: equipmentAllLoading } = useAllEquipment();
  const { data: equipmentSite = [], isLoading: equipmentSiteLoading } = useEquipment(selectedSiteId ?? undefined);
  const { data: pointsAll = [] } = useAllPoints();
  const { data: pointsSite = [] } = usePoints(selectedSiteId ?? undefined);
  const { data: faultsAll = [] } = useActiveFaults();
  const { data: faultsSite = [] } = useSiteFaults(selectedSiteId ?? undefined);
  const { data: sites = [] } = useSites();
  const { data: capabilities } = useCapabilities();
  const aiAvailable = capabilities?.ai_available === true;

  const equipment = selectedSiteId ? equipmentSite : equipmentAll;
  const points = selectedSiteId ? pointsSite : pointsAll;
  const faults = selectedSiteId ? faultsSite : faultsAll;
  const equipmentLoading = selectedSiteId ? equipmentSiteLoading : equipmentAllLoading;
  const siteMap = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);
  const appendAiMessage = useCallback(
    (msg: { role: "user" | "assistant"; content: string }) =>
      setAiMessages((prev) => [...prev, msg].slice(-100)),
    [],
  );
  /** site_id to send to tag-with-openai: one site → that site; multiple → tagSpecificSite ? tagSiteId : null */
  const tagWithAiSiteId = useMemo(() => {
    if (sites.length === 0) return null;
    if (sites.length === 1) return sites[0].id;
    return tagSpecificSite ? (tagSiteId ?? sites[0]?.id ?? null) : null;
  }, [sites, tagSpecificSite, tagSiteId]);

  const { data: exportData, isLoading: exportLoading } = useQuery<DataModelExportRow[]>({
    queryKey: ["data-model", "export"],
    queryFn: () => apiFetch<DataModelExportRow[]>("/data-model/export"),
    staleTime: 60 * 1000,
  });

  const importMutation = useMutation<DataModelImportResponse, Error, DataModelImportBody>({
    mutationFn: (body) =>
      apiFetch<DataModelImportResponse>("/data-model/import", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: (data) => {
      setImportError(null);
      setImportResult(data);
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["faults"] });
    },
    onError: (err: Error) => {
      setImportError(err.message);
      setImportResult(null);
    },
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
    onMutate: () => {
      setAiTagPhase("running");
      setAiTagStatus("Tagging started. Calling Open‑Claw and preparing import JSON...");
      setAiTagError(null);
      setAiTagResult(null);
    },
    onSuccess: (data) => {
      setAiTagResult(data);
      setAiTagError(null);
      setAiTagPhase("success");
      // Pre-fill import textarea so user can review the exact tagged payload.
      const payload = { points: data.points, equipment: data.equipment };
      setImportJson(JSON.stringify(payload, null, 2));

      if (data.meta.import_result) {
        setAiTagStatus(
          `Tagging complete. Auto-import finished: Created ${data.meta.import_result.created ?? 0}, Updated ${data.meta.import_result.updated ?? 0}.`
        );
        setImportResult(data.meta.import_result);
        queryClient.invalidateQueries({ queryKey: ["data-model"] });
        queryClient.invalidateQueries({ queryKey: ["sites"] });
        queryClient.invalidateQueries({ queryKey: ["equipment"] });
        queryClient.invalidateQueries({ queryKey: ["points"] });
        queryClient.invalidateQueries({ queryKey: ["faults"] });
      } else {
        setAiTagStatus("Tagging complete. Review the generated JSON in Import and click Import when ready.");
      }

      const summaryParts: string[] = [];
      summaryParts.push(
        `I tagged ${data.meta.point_count} points and ${data.meta.equipment_count} equipment using ${data.meta.model}.`
      );
      if (data.meta.import_result) {
        summaryParts.push(
          `Auto-import created ${data.meta.import_result.created ?? 0} and updated ${data.meta.import_result.updated ?? 0} items.`
        );
      } else {
        summaryParts.push("Review the proposed tags below, then click Import when you're satisfied.");
      }
      appendAiMessage({
        role: "assistant",
        content: summaryParts.join(" "),
      });
    },
    onError: (err) => {
      let msg = err.message;
      if (msg.includes("Equipment name") && msg.includes("not found for site")) {
        msg =
          "I tried to tag using an equipment name (for example 'VAV-1') that does not exist for this site. " +
          "Create that equipment in Step 2 (Sites/Equipment) or adjust the names/UUIDs in the data model, then try tagging again.";
      }
      setAiTagError(msg);
      setAiTagResult(null);
      setAiTagPhase("error");
      setAiTagStatus("Tagging failed. See assistant message below.");
      appendAiMessage({
        role: "assistant",
        content: msg,
      });
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

  // Open‑Claw-only: there is no client-side LLM API key input.

  // When multiple sites, keep tagSiteId in sync (default to selected site or first)
  useEffect(() => {
    if (sites.length <= 1) return;
    const ids = new Set(sites.map((s) => s.id));
    if (!tagSiteId || !ids.has(tagSiteId)) {
      setTagSiteId(selectedSiteId && ids.has(selectedSiteId) ? selectedSiteId : sites[0]?.id ?? null);
    }
  }, [sites, selectedSiteId, tagSiteId]);

  const handleImport = () => {
    try {
      const parsed = JSON.parse(importJson) as DataModelImportBody | DataModelExportRow[];
      const body: DataModelImportBody = Array.isArray(parsed) ? { points: parsed } : parsed;
      if (!body.points?.length) {
        setImportError(null);
        setImportResult({ total: 0, warnings: ["No points in payload"] });
        return;
      }
      setImportError(null);
      importMutation.mutate(body);
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Invalid JSON");
      setImportResult(null);
    }
  };

  const handleTagWithAi = () => {
    if (!aiAvailable) {
      setAiTagPhase("error");
      setAiTagStatus("AI disabled. Run bootstrap with --with-open-claw and set OFDD_OPEN_CLAW_BASE_URL + OFDD_OPEN_CLAW_API_KEY.");
      return;
    }
    setAiTagError(null);
    setAiTagResult(null);
    const question = agentChatPrompt?.trim() || "Tag current data model for Brick types and feeds/fed_by.";
    appendAiMessage({ role: "user", content: question });
    tagWithAiMutation.mutate({
      site_id: tagWithAiSiteId,
      model: openAiModel,
      auto_import: true,
      user_summary: agentChatPrompt?.trim() || undefined,
      max_retries: 3,
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
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Data Model Setup</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Build your Brick + BACnet data model step by step below. Export JSON for AI tagging, paste tagged JSON back to import, and run
        SPARQL queries to validate.
      </p>

      {/* Step-by-step guide — matches Open-FDD README workflow */}
      <Card className="mb-8 border-primary/20 bg-primary/5">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-lg">
            <ListOrdered className="h-5 w-5" />
            How to build your data model
          </CardTitle>
          <p className="text-sm font-normal text-muted-foreground">
            Follow these steps in order. Check the Open-FDD README in the git repo for the latest LLM prompt.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="list-decimal space-y-3 pl-5 text-sm">
            <li>
              <strong>BACnet Who-Is</strong> — Run Who-Is below to find devices on your network (start/end instance range).
            </li>
            <li>
              <strong>Point discovery + Add to RDF</strong> — For each device, enter its instance, run <strong>Point discovery</strong>, then <strong>Add to data model</strong> to merge BACnet into the graph. Repeat device by device.
            </li>
            <li>
              <strong>Add a site (Step 2)</strong> — In the Sites section below BACnet discover and add to model, create a site if you don’t have one. Assign points to it when you import.
            </li>
            <li>
              <strong>Export JSON and open your LLM</strong> — Download the export (Export section below), then open your LLM chat. Get the prompt from the Open-FDD README in the git repo and paste it into the LLM. Upload your <strong>fault rule YAML files</strong> (from the Faults page) so the LLM knows which points your rules need.
            </li>
            <li>
              <strong>Chat with the LLM</strong> — Paste the exported JSON into the LLM. Confirm with the LLM that Brick types, feeds/fed-by, and rule_input are correct before asking for the final JSON.
            </li>
            <li>
              <strong>Apply back in Open-FDD</strong> — Copy the LLM’s JSON output and paste it into the “Paste from AI” section below (or choose a JSON file), then click <strong>Apply to data model</strong>.
            </li>
            <li>
              <strong>SPARQL test</strong> — Use the Data Model Testing page to run predefined summary queries (e.g. count AHUs, chillers) or your own SPARQL to confirm the data model returns the relationships and points you need for your algorithms and fault rules.
            </li>
          </ol>
        </CardContent>
      </Card>

      <BacnetDiscoveryPanel />

      {/* Step 2: Sites — add a site so you can assign points when you import */}
      <Card className="mt-6">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Building2 className="h-5 w-5" />
                <span className="text-base font-medium text-muted-foreground">Step 2</span>
                Sites
              </CardTitle>
              <p className="text-sm font-normal text-muted-foreground">
                Create a site if you don’t have one. Assign points to it when you import.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
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

      {/* Data model TTL — view, serialize, check (kept near BACnet workflow) */}
      <Card className="mt-6">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-lg">
            <FileText className="h-5 w-5" />
            Data model (TTL)
          </CardTitle>
          <p className="text-sm font-normal text-muted-foreground">
            View full Brick + BACnet graph as TTL, serialize to file, or run integrity check.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
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
        </CardContent>
      </Card>

        <div className="mt-6 space-y-6">

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
              GET /data-model/export — BACnet discovery + DB points. Download JSON for manual
              export to an external LLM (copy-paste there, then re-import below), or use the in-house
              Open‑Claw API Assist to chat with the agent and tag via the same API.
            </p>
            {exportLoading && <Skeleton className="h-48 w-full rounded-lg" />}
            {!exportLoading && exportJson && (
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => exportData && downloadJson(exportData, "data-model-export.json")}
                    className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted self-start"
                    title="Download full export as JSON file for manual tagging in an external LLM"
                  >
                    <Download className="h-4 w-4" />
                    Download JSON
                  </button>
                  {aiAvailable ? (
                    <button
                      type="button"
                      onClick={() => setShowAiAssist((v) => !v)}
                      className="inline-flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-medium transition-colors hover:bg-primary/20 self-start"
                      data-testid="openai-assist-toggle"
                    >
                      <Sparkles className="h-4 w-4" />
                      {showAiAssist ? "Hide Open‑Claw Assist" : "Open‑Claw API Assist"}
                    </button>
                  ) : (
                    <span className="self-start text-xs text-muted-foreground">
                      AI disabled (bootstrap with `--with-open-claw`).
                    </span>
                  )}
                </div>
                {aiAvailable && showAiAssist && (
                  <div className="mt-2 space-y-3 rounded-lg border border-border/60 bg-card/70 p-4">
                    <p className="text-sm text-muted-foreground">
                      In-house agent: describe your HVAC system and feeds/fed_by in the chat below. The agent calls the same export/import API with retries; then validate on the Data Model Testing tab and pass/fail the result.
                    </p>
                    <div className="h-56 overflow-y-auto rounded-md border bg-muted/40 p-3 text-xs space-y-2">
                      {aiMessages.length === 0 ? (
                        <p className="italic text-muted-foreground">
                          e.g. “Anything need to be tagged or is it good enough? AHU feeds VAV and VAV feeds zone temp; also set fed_by relationships.”
                        </p>
                      ) : (
                        aiMessages.map((m, idx) => (
                          <div
                            key={idx}
                            className={`max-w-[90%] rounded-md px-2 py-1 ${
                              m.role === "user"
                                ? "ml-auto bg-primary text-primary-foreground"
                                : "mr-auto w-full max-w-md bg-background border text-foreground"
                            }`}
                          >
                            <div className="whitespace-pre-wrap text-xs">{m.content}</div>
                          </div>
                        ))
                      )}
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">Chat prompt (describe HVAC and relationships for AI to tag)</label>
                      <textarea
                        value={agentChatPrompt}
                        onChange={(e) => setAgentChatPrompt(e.target.value)}
                        placeholder="Describe HVAC system and feeds or fed by relationships for AI to tag"
                        rows={3}
                        className="w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        data-testid="openai-assist-chat-prompt"
                      />
                    </div>
                    <div className="grid gap-3 md:grid-cols-1">
                      <div>
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">Model</label>
                        <select
                          value={openAiModel}
                          onChange={(e) => setOpenAiModel(e.target.value)}
                          className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                        >
                          {AI_MODEL_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-4 text-sm">
                      {sites.length === 1 && (
                        <span className="text-muted-foreground">
                          Tagging your only site ({sites[0].name}).
                        </span>
                      )}
                      {sites.length > 1 && (
                        <>
                          <label className="inline-flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={tagSpecificSite}
                              onChange={(e) => setTagSpecificSite(e.target.checked)}
                              data-testid="tag-specific-site-checkbox"
                            />
                            Tag specific site
                          </label>
                          {tagSpecificSite && (
                            <select
                              value={tagSiteId ?? ""}
                              onChange={(e) => setTagSiteId(e.target.value || null)}
                              className="h-9 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                              data-testid="tag-site-select"
                            >
                              {sites.map((s) => (
                                <option key={s.id} value={s.id}>
                                  {s.name}
                                </option>
                              ))}
                            </select>
                          )}
                        </>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={handleTagWithAi}
                        disabled={tagWithAiMutation.isPending || !aiAvailable}
                        className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                        data-testid="openai-assist-run"
                      >
                        <Sparkles className="h-4 w-4" />
                        {tagWithAiMutation.isPending ? "Tagging..." : "Tag with Open‑Claw"}
                      </button>
                      {aiTagResult && (
                        <span className="text-sm text-muted-foreground">
                          Tagged {aiTagResult.meta.point_count} points, {aiTagResult.meta.equipment_count} equipment with {aiTagResult.meta.model}.
                        </span>
                      )}
                    </div>
                    {aiTagPhase !== "idle" && (
                      <div
                        className={`rounded-lg border px-3 py-2 text-sm ${
                          aiTagPhase === "running"
                            ? "border-primary/40 bg-primary/10 text-primary"
                            : aiTagPhase === "success"
                              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                              : "border-destructive/40 bg-destructive/10 text-destructive"
                        }`}
                        data-testid="openai-assist-status"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`h-2.5 w-2.5 rounded-full ${
                              aiTagPhase === "running"
                                ? "animate-pulse bg-primary"
                                : aiTagPhase === "success"
                                  ? "bg-emerald-500"
                                  : "bg-destructive"
                            }`}
                          />
                          <span>{aiTagStatus}</span>
                        </div>
                        {aiTagPhase === "running" && (
                          <p className="mt-1 text-xs opacity-80">
                            Large payloads may take up to a minute depending on model and point count.
                          </p>
                        )}
                      </div>
                    )}
                    {aiTagError && (
                      <div className="space-y-1">
                        <p className="text-sm text-destructive">{aiTagError}</p>
                        {aiTagError.includes("Missing site") && (
                          <p className="text-xs text-muted-foreground">
                            The AI returned a site ID that isn’t in your database. Create the site in <strong>Step 2 (Sites)</strong>, or if you have multiple sites turn on <strong>Tag specific site</strong> and pick the site in the dropdown, then try again.
                          </p>
                        )}
                        {aiTagError.includes("500") && !aiTagError.includes("Missing site") && (
                          <p className="text-xs text-muted-foreground">
                            If the message is unclear, ensure the backend has the <code className="rounded bg-muted px-1">openai</code> package:{" "}
                            <code className="rounded bg-muted px-1">pip install &apos;openai&gt;=1.0&apos;</code> or{" "}
                            <code className="rounded bg-muted px-1">pip install -e &apos;.[platform]&apos;</code>.
                          </p>
                        )}
                      </div>
                    )}
                    {aiTagResult?.meta?.agent_log && aiTagResult.meta.agent_log.length > 0 && (
                      <div className="rounded-lg border border-border/60 bg-muted/30 p-3">
                        <p className="mb-2 text-xs font-medium text-muted-foreground">Agent log</p>
                        <ul className="max-h-48 list-inside list-disc space-y-1 overflow-auto text-xs font-mono">
                          {aiTagResult.meta.agent_log.map((entry, i) => (
                            <li key={i}>
                              <span className="font-medium">{entry.step}</span>
                              {entry.attempt != null && ` (attempt ${entry.attempt})`}
                              {entry.detail && ` — ${entry.detail}`}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            {!exportLoading && (!exportData || exportData.length === 0) && (
              <p className="text-sm text-muted-foreground">No points in the data model yet.</p>
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
            {importError && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                <span className="font-medium">Import failed:</span> {importError}
              </div>
            )}
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

        {/* Remove all / Reset graph — destructive actions at bottom */}
        <Card className="border-amber-500/30">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg text-amber-700 dark:text-amber-400">
              <Trash2 className="h-5 w-5" />
              Remove all sites / Reset graph
            </CardTitle>
            <p className="text-sm font-normal text-muted-foreground">
              Irreversible. Use only when clearing the data model or resetting the in-memory graph to DB-only.
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            {sites.length > 0 && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
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
            <div className="rounded-lg border border-border/60 p-4">
              <p className="mb-3 text-sm text-muted-foreground">
                Serialize in-memory graph to TTL file; reset graph to DB-only (clears BACnet); run integrity check.
              </p>
              <div className="flex flex-wrap items-center gap-3">
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
              {resetMutation.isSuccess && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {(resetMutation.data as { message?: string })?.message ?? "Graph reset."}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
