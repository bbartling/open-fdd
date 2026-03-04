import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Check, Play, Database, Upload, Code } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
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
  const [importJson, setImportJson] = useState("");
  const [importResult, setImportResult] = useState<DataModelImportResponse | null>(null);
  const [sparqlQuery, setSparqlQuery] = useState(DEFAULT_SPARQL);
  const [sparqlError, setSparqlError] = useState<string | null>(null);

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
      </div>
    </div>
  );
}
