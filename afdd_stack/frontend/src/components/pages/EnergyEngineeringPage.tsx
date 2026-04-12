import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Database, ListOrdered, Upload } from "lucide-react";
import { EnergyCalcsTree } from "@/components/site/EnergyCalcsTree";
import { useSiteContext } from "@/contexts/site-context";
import { useEquipment } from "@/hooks/use-sites";
import {
  createEnergyCalculation,
  deleteEnergyCalculation,
  exportEnergyCalculations,
  importEnergyCalculations,
  listEnergyCalculations,
  listEnergyCalcTypes,
  previewEnergyCalculation,
  seedDefaultPenaltyCatalog,
  updateEnergyCalculation,
} from "@/lib/crud-api";
import type {
  EnergyCalcFieldSpec,
  EnergyCalcTypePublic,
  EnergyCalculationsImportBody,
  EnergyPreviewResult,
} from "@/types/api";
import { EquipmentMetadataTab } from "./equipment-metadata-tab";

const DOCS_ENERGY_AI =
  "https://bbartling.github.io/open-fdd/modeling/ai_assisted_energy_calculations";
const DOCS_ENERGY_PENALTY =
  "https://bbartling.github.io/open-fdd/modeling/energy_penalty_equations";

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function EnergyAiWorkflowCard({ siteId }: { siteId: string }) {
  const queryClient = useQueryClient();
  const location = useLocation();
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<string | null>(null);
  const [seedMsg, setSeedMsg] = useState<string | null>(null);

  const exportMut = useMutation({
    mutationFn: () => exportEnergyCalculations(siteId),
    onSuccess: (data) => {
      downloadJson(data, `energy-calculations-export-${siteId.slice(0, 8)}.json`);
    },
  });

  const seedMut = useMutation({
    mutationFn: (replace: boolean) => seedDefaultPenaltyCatalog(siteId, replace),
    onSuccess: (res) => {
      setSeedMsg(
        `Seeded ${res.created} default penalty rows (${res.rows_in_catalog} in catalog). ` +
          (res.deleted_before_insert ? `Removed ${res.deleted_before_insert} prior defaults. ` : "") +
          "Rows start disabled — enable and bind points in the tree.",
      );
      void queryClient.invalidateQueries({ queryKey: ["energy-calculations", siteId] });
      void queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
    onError: (e: Error) => {
      setSeedMsg(`Seed failed: ${e.message}`);
    },
  });

  const importMut = useMutation({
    mutationFn: async (raw: string) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch (parseErr) {
        const msg =
          parseErr instanceof SyntaxError && parseErr.message
            ? `Invalid JSON (${parseErr.message}). Please check the file or paste valid JSON.`
            : "Invalid JSON: please check the file or paste valid JSON.";
        throw new Error(msg);
      }
      let body: EnergyCalculationsImportBody;
      if (Array.isArray(parsed)) {
        body = {
          site_id: siteId,
          energy_calculations: parsed as EnergyCalculationsImportBody["energy_calculations"],
        };
      } else if (parsed && typeof parsed === "object" && "energy_calculations" in parsed) {
        const o = parsed as Record<string, unknown>;
        const rows = o.energy_calculations;
        if (!Array.isArray(rows)) throw new Error("energy_calculations must be an array.");
        const sid = o.site_id != null ? String(o.site_id) : siteId;
        if (sid !== siteId) {
          throw new Error("Export site_id does not match the site selected in the header. Switch site or fix JSON.");
        }
        body = {
          site_id: siteId,
          energy_calculations: rows as EnergyCalculationsImportBody["energy_calculations"],
        };
      } else {
        throw new Error('Expected Open-FDD export object with "energy_calculations" or a JSON array of rows.');
      }
      return importEnergyCalculations(body);
    },
    onSuccess: (res) => {
      setImportError(null);
      setImportResult(`Imported: ${res.created} created, ${res.updated} updated (${res.total} rows).`);
      void queryClient.invalidateQueries({ queryKey: ["energy-calculations", siteId] });
      void queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
    onError: (e: Error) => {
      setImportResult(null);
      setImportError(e.message);
    },
  });

  return (
    <Card className="border-primary/15 bg-primary/[0.03]">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-lg">
          <ListOrdered className="h-5 w-5" />
          AI-assisted energy calculations
        </CardTitle>
        <p className="text-sm font-normal text-muted-foreground">
          After{" "}
          <Link
            to={{ pathname: "/data-model", search: location.search }}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            AI-assisted data modeling
          </Link>
          , export this site&apos;s calculation specs for an external LLM, then import the edited JSON. Full prompt and
          schema:{" "}
          <a
            href={DOCS_ENERGY_AI}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            docs — AI-assisted energy calculations
          </a>{" "}
          and the{" "}
          <a
            href={DOCS_ENERGY_PENALTY}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            default penalty equation catalog
          </a>
          .
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            Complete Brick/point tagging with{" "}
            <strong>GET /data-model/export</strong> → LLM → <strong>PUT /data-model/import</strong> (see Data Model
            BRICK).
          </li>
          <li>
            Download the bundle below (includes <code className="rounded bg-muted px-1 text-xs">calc_types</code> field
            definitions for each predefined calculator).
          </li>
          <li>
            Paste the JSON into your LLM with the documentation prompt; ask for updated{" "}
            <code className="rounded bg-muted px-1 text-xs">energy_calculations</code> only, using valid{" "}
            <code className="rounded bg-muted px-1 text-xs">calc_type</code> ids and parameter keys from the bundle.
          </li>
          <li>Paste the LLM output here and click Apply import (same site as in the header).</li>
        </ol>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => exportMut.mutate()}
            disabled={exportMut.isPending}
            className="inline-flex items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
          >
            <Database className="h-4 w-4" />
            {exportMut.isPending ? "Preparing…" : "Download export JSON"}
          </button>
          <button
            type="button"
            onClick={() => {
              setSeedMsg(null);
              seedMut.mutate(false);
            }}
            disabled={seedMut.isPending}
            className="inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-4 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/15 disabled:opacity-50"
          >
            {seedMut.isPending ? "Seeding…" : "Seed default penalty catalog (18)"}
          </button>
          <button
            type="button"
            title="Deletes existing penalty_default_* rows for this site, then inserts 18 fresh defaults."
            onClick={() => {
              if (
                !window.confirm(
                  "Replace all default penalty rows (penalty_default_*) for this site? This deletes existing defaults before re-inserting.",
                )
              ) {
                return;
              }
              setSeedMsg(null);
              seedMut.mutate(true);
            }}
            disabled={seedMut.isPending}
            className="inline-flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm font-medium text-destructive transition-colors hover:bg-destructive/15 disabled:opacity-50"
          >
            Replace &amp; re-seed defaults
          </button>
        </div>
        {seedMsg && <p className="text-sm text-muted-foreground">{seedMsg}</p>}
        {exportMut.isError && (
          <p className="text-sm text-destructive">{(exportMut.error as Error).message}</p>
        )}
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Paste from AI (full export with <code className="rounded bg-muted px-1 text-xs">energy_calculations</code>, or
            only the <code className="rounded bg-muted px-1 text-xs">energy_calculations</code> array — site must match the
            header).
          </p>
          <textarea
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            className="h-36 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            spellCheck={false}
            placeholder='{ "format": "openfdd_energy_calculations_v1", "energy_calculations": [ ... ] }'
          />
          <button
            type="button"
            onClick={() => {
              setImportError(null);
              setImportResult(null);
              importMut.mutate(importText);
            }}
            disabled={importMut.isPending || !importText.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            <Upload className="h-4 w-4" />
            {importMut.isPending ? "Applying…" : "Apply import"}
          </button>
          {importError && <p className="text-sm text-destructive">{importError}</p>}
          {importResult && <p className="text-sm text-muted-foreground">{importResult}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function slugFromName(name: string): string {
  const s = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return s || "energy_calc";
}

function defaultsFromFields(fields: EnergyCalcFieldSpec[]): Record<string, string> {
  const o: Record<string, string> = {};
  for (const f of fields) {
    if (f.default !== undefined && f.default !== null) o[f.key] = String(f.default);
    else o[f.key] = "";
  }
  return o;
}

type BuildParametersResult = {
  parameters: Record<string, unknown>;
  /** Field keys with invalid float text (non-empty but not parseable as a number). */
  errors: Record<string, string>;
};

function buildParametersFromForm(fields: EnergyCalcFieldSpec[], raw: Record<string, string>): BuildParametersResult {
  const parameters: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const v = raw[f.key]?.trim() ?? "";
    if (v === "") continue;
    if (f.type === "float") {
      const n = Number(v);
      if (Number.isNaN(n)) errors[f.key] = "Enter a valid number.";
      else parameters[f.key] = n;
    } else if (f.type === "enum") {
      parameters[f.key] = v;
    } else {
      parameters[f.key] = v;
    }
  }
  return { parameters, errors };
}

function assertNoParamErrors(result: BuildParametersResult): Record<string, unknown> {
  if (Object.keys(result.errors).length === 0) return result.parameters;
  const err = new Error("Invalid numeric parameter values.") as Error & {
    paramFieldErrors: Record<string, string>;
  };
  err.paramFieldErrors = result.errors;
  throw err;
}

function DeleteEnergyCalcDialog({
  target,
  onCancel,
  onConfirm,
  disabled,
}: {
  target: { id: string; name: string };
  onCancel: () => void;
  onConfirm: () => void;
  disabled: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = panelRef.current;
    el?.querySelector<HTMLButtonElement>("button[data-autofocus]")?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4"
      role="presentation"
      onClick={onCancel}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="eecalc-delete-title"
        className="max-w-md rounded-lg border border-border bg-card p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key !== "Tab") return;
          const root = panelRef.current;
          if (!root) return;
          const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>("button")).filter(
            (b) => !b.disabled,
          );
          if (buttons.length === 0) return;
          const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
          if (e.shiftKey) {
            if (i <= 0) {
              e.preventDefault();
              buttons[buttons.length - 1]?.focus();
            }
          } else if (i === buttons.length - 1 || i === -1) {
            e.preventDefault();
            buttons[0]?.focus();
          }
        }}
      >
        <h2 id="eecalc-delete-title" className="text-lg font-semibold">
          Delete calculation?
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          This removes{" "}
          <span className="font-medium text-foreground">{target.name || target.id}</span> from this site. This cannot be
          undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            data-autofocus
            className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground disabled:opacity-50"
            disabled={disabled}
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

function EnergyCalculationWorkbench() {
  const queryClient = useQueryClient();
  const { selectedSiteId } = useSiteContext();
  const { data: siteEquipment = [] } = useEquipment(selectedSiteId ?? undefined);

  const typesQuery = useQuery({
    queryKey: ["energy-calc-types"],
    queryFn: listEnergyCalcTypes,
  });

  const calcTypes = useMemo(() => typesQuery.data?.calc_types ?? [], [typesQuery.data]);
  const [calcTypeId, setCalcTypeId] = useState<string>("");
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [externalId, setExternalId] = useState("");
  const [equipmentId, setEquipmentId] = useState<string>("");
  const [pointBindingsText, setPointBindingsText] = useState("{}");
  const [preview, setPreview] = useState<EnergyPreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [paramFieldErrors, setParamFieldErrors] = useState<Record<string, string>>({});

  const effectiveCalcTypeId = useMemo(() => {
    if (!calcTypes.length) return "";
    if (calcTypeId && calcTypes.some((c) => c.id === calcTypeId)) return calcTypeId;
    return calcTypes[0].id;
  }, [calcTypes, calcTypeId]);

  const activeSpec: EnergyCalcTypePublic | undefined = useMemo(
    () => calcTypes.find((c) => c.id === effectiveCalcTypeId),
    [calcTypes, effectiveCalcTypeId],
  );

  const mergedParamValues = useMemo(() => {
    if (!activeSpec) return paramValues;
    return { ...defaultsFromFields(activeSpec.fields), ...paramValues };
  }, [activeSpec, paramValues]);

  const onCalcTypeChange = useCallback(
    (id: string) => {
      setCalcTypeId(id);
      const spec = calcTypes.find((c) => c.id === id);
      if (spec) setParamValues(defaultsFromFields(spec.fields));
      setPreview(null);
      setPreviewError(null);
      setParamFieldErrors({});
    },
    [calcTypes],
  );

  const listQuery = useQuery({
    queryKey: ["energy-calculations", selectedSiteId],
    queryFn: () => listEnergyCalculations(selectedSiteId!),
    enabled: Boolean(selectedSiteId),
  });

  const previewMut = useMutation({
    mutationFn: async () => {
      if (!activeSpec) throw new Error("No calculation type selected.");
      const built = buildParametersFromForm(activeSpec.fields, mergedParamValues);
      const parameters = assertNoParamErrors(built);
      return previewEnergyCalculation(effectiveCalcTypeId, parameters);
    },
    onSuccess: (data) => {
      setPreview(data);
      setPreviewError(null);
      setParamFieldErrors({});
    },
    onError: (e: Error) => {
      setPreview(null);
      const pe = (e as Error & { paramFieldErrors?: Record<string, string> }).paramFieldErrors;
      if (pe && Object.keys(pe).length > 0) {
        setParamFieldErrors(pe);
        setPreviewError("Fix invalid numbers in the highlighted fields.");
      } else {
        setParamFieldErrors({});
        setPreviewError(e.message);
      }
    },
  });

  const createMut = useMutation({
    mutationFn: async () => {
      if (!selectedSiteId) throw new Error("Select a site first.");
      if (!activeSpec) throw new Error("No calculation type selected.");
      let point_bindings: Record<string, unknown>;
      try {
        const parsed = JSON.parse(pointBindingsText.trim() === "" ? "{}" : pointBindingsText);
        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Point bindings must be a JSON object.");
        }
        point_bindings = parsed as Record<string, unknown>;
      } catch (e) {
        if (e instanceof SyntaxError) {
          throw new Error(`Point bindings: invalid JSON (${e.message})`);
        }
        throw e;
      }
      const parameters = assertNoParamErrors(buildParametersFromForm(activeSpec.fields, mergedParamValues));
      const ext = externalId.trim() || slugFromName(name);
      if (!ext) throw new Error("Name or external id is required.");
      const body = {
        site_id: selectedSiteId,
        equipment_id: equipmentId.trim() || null,
        external_id: ext,
        name: name.trim() || ext,
        description: description.trim() || null,
        calc_type: effectiveCalcTypeId,
        parameters,
        point_bindings,
        enabled: true,
      };
      return createEnergyCalculation(body);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["energy-calculations", selectedSiteId] });
      void queryClient.invalidateQueries({ queryKey: ["data-model"] });
      setName("");
      setDescription("");
      setExternalId("");
      setPreview(null);
      setParamFieldErrors({});
    },
    onError: (e: Error) => {
      const pe = (e as Error & { paramFieldErrors?: Record<string, string> }).paramFieldErrors;
      if (pe && Object.keys(pe).length > 0) setParamFieldErrors(pe);
      else setParamFieldErrors({});
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteEnergyCalculation(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["energy-calculations", selectedSiteId] });
      void queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });

  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  const patchMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateEnergyCalculation(id, { enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["energy-calculations", selectedSiteId] });
      void queryClient.invalidateQueries({ queryKey: ["data-model"] });
    },
  });

  if (!selectedSiteId) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a site in the header. Energy calculations are stored per site—each building has different equipment,
        points, and savings logic, so nothing here applies globally.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        Define FDD-oriented savings estimates for <strong>this site only</strong>. Saved rows sync to Postgres and into{" "}
        <code className="rounded bg-muted px-1 text-xs">config/data_model.ttl</code> as{" "}
        <code className="rounded bg-muted px-1 text-xs">ofdd:EnergyCalculation</code> linked with{" "}
        <code className="rounded bg-muted px-1 text-xs">brick:isPartOf</code> the site. Preview uses static inputs;
        interval and fault-duration analytics are planned separately.
      </p>

      {typesQuery.isError && (
        <p className="text-sm text-destructive">Could not load calculation types: {(typesQuery.error as Error).message}</p>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Calculations by equipment</CardTitle>
          <p className="text-xs font-normal text-muted-foreground">
            Tree matches site equipment; site-level calcs are not tied to a device. Use the row actions menu (⋮) or
            right-click a row for Enable, Disable, or Delete (same idea as the Points page).
          </p>
        </CardHeader>
        <CardContent>
          {listQuery.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {listQuery.isError && (
            <p className="text-sm text-destructive">{(listQuery.error as Error).message}</p>
          )}
          {listQuery.data && (
            <>
              <EnergyCalcsTree
                equipment={siteEquipment}
                calculations={listQuery.data}
                onSetEnabled={(id, enabled) => patchMut.mutate({ id, enabled })}
                onDeleteCalc={(id, name) => setDeleteTarget({ id, name })}
              />
              {deleteTarget && (
                <DeleteEnergyCalcDialog
                  target={deleteTarget}
                  onCancel={() => setDeleteTarget(null)}
                  disabled={deleteMut.isPending}
                  onConfirm={() => {
                    deleteMut.mutate(deleteTarget.id, {
                      onSettled: () => setDeleteTarget(null),
                    });
                  }}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>

      <EnergyAiWorkflowCard siteId={selectedSiteId} />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">New calculation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="block text-sm" htmlFor="eecalc-type">
            <span className="mb-1 block text-xs text-muted-foreground">Calculation type</span>
            <select
              id="eecalc-type"
              className="h-9 w-full max-w-xl rounded-lg border border-border/60 bg-background px-3 text-sm"
              value={effectiveCalcTypeId}
              onChange={(e) => onCalcTypeChange(e.target.value)}
              disabled={!calcTypes.length}
            >
              {calcTypes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          {activeSpec && (
            <p className="text-xs text-muted-foreground">
              {activeSpec.summary} <span className="opacity-70">({activeSpec.category})</span>
            </p>
          )}

          <div className="grid max-w-xl grid-cols-1 gap-3 md:grid-cols-2">
            <label className="text-sm" htmlFor="eecalc-name">
              <span className="mb-1 block text-xs text-muted-foreground">Display name</span>
              <input
                id="eecalc-name"
                value={name}
                onChange={(e) => {
                  const v = e.target.value;
                  const prevSlug = slugFromName(name);
                  setName(v);
                  setExternalId((ex) => {
                    const nextSlug = slugFromName(v);
                    if (!ex.trim() || ex === prevSlug) return nextSlug;
                    return ex;
                  });
                }}
                className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
                placeholder="e.g. AHU-1 excess OA heating"
              />
            </label>
            <label className="text-sm" htmlFor="eecalc-extid">
              <span className="mb-1 block text-xs text-muted-foreground">External id (unique per site)</span>
              <input
                id="eecalc-extid"
                value={externalId}
                onChange={(e) => setExternalId(e.target.value)}
                className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
                placeholder="slug"
              />
            </label>
          </div>

          <label className="block text-sm" htmlFor="eecalc-desc">
            <span className="mb-1 block text-xs text-muted-foreground">Description (optional)</span>
            <input
              id="eecalc-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="h-9 w-full max-w-2xl rounded-lg border border-border/60 bg-background px-3 text-sm"
            />
          </label>

          <label className="block text-sm" htmlFor="eecalc-eq">
            <span className="mb-1 block text-xs text-muted-foreground">Equipment (optional)</span>
            <select
              id="eecalc-eq"
              className="h-9 w-full max-w-xl rounded-lg border border-border/60 bg-background px-3 text-sm"
              value={equipmentId}
              onChange={(e) => setEquipmentId(e.target.value)}
            >
              <option value="">— Site-level (not tied to one asset) —</option>
              {siteEquipment.map((eq) => (
                <option key={eq.id} value={eq.id}>
                  {eq.name} ({eq.equipment_type ?? "Equipment"})
                </option>
              ))}
            </select>
          </label>

          {activeSpec && (
            <div className="grid max-w-3xl grid-cols-1 gap-3 md:grid-cols-2">
              {activeSpec.fields.map((f) => {
                const id = `eecalc-field-${f.key}`;
                if (f.type === "enum" && f.options?.length) {
                  return (
                    <label key={f.key} className="text-sm" htmlFor={id}>
                      <span className="mb-1 block text-xs text-muted-foreground">{f.label}</span>
                      <select
                        id={id}
                        className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
                        value={mergedParamValues[f.key] ?? ""}
                        onChange={(e) => setParamValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                      >
                        <option value="">—</option>
                        {f.options.map((opt) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                }
                return (
                  <label key={f.key} className="text-sm" htmlFor={id}>
                    <span className="mb-1 block text-xs text-muted-foreground">
                      {f.label}
                      {f.min != null || f.max != null ? (
                        <span className="opacity-70">
                          {" "}
                          ({f.min != null ? `min ${f.min}` : ""}
                          {f.min != null && f.max != null ? ", " : ""}
                          {f.max != null ? `max ${f.max}` : ""})
                        </span>
                      ) : null}
                    </span>
                    <input
                      id={id}
                      type="text"
                      inputMode="decimal"
                      value={mergedParamValues[f.key] ?? ""}
                      onChange={(e) => {
                        const v = e.target.value;
                        setParamValues((prev) => ({ ...prev, [f.key]: v }));
                        if (f.type === "float") {
                          setParamFieldErrors((prev) => {
                            if (!prev[f.key]) return prev;
                            const next = { ...prev };
                            delete next[f.key];
                            return next;
                          });
                        }
                      }}
                      aria-invalid={Boolean(paramFieldErrors[f.key])}
                      className={`h-9 w-full rounded-lg border bg-background px-3 text-sm font-mono ${
                        paramFieldErrors[f.key] ? "border-destructive" : "border-border/60"
                      }`}
                    />
                    {paramFieldErrors[f.key] ? (
                      <span className="mt-1 block text-xs text-destructive">{paramFieldErrors[f.key]}</span>
                    ) : null}
                  </label>
                );
              })}
            </div>
          )}

          <label className="block text-sm" htmlFor="eecalc-pb">
            <span className="mb-1 block text-xs text-muted-foreground">Point bindings JSON (optional)</span>
            <textarea
              id="eecalc-pb"
              value={pointBindingsText}
              onChange={(e) => setPointBindingsText(e.target.value)}
              className="h-24 w-full max-w-2xl rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-xs"
              spellCheck={false}
            />
          </label>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => previewMut.mutate()}
              disabled={previewMut.isPending || !activeSpec}
              className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {previewMut.isPending ? "Preview…" : "Preview"}
            </button>
            <button
              type="button"
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending || !activeSpec}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {createMut.isPending ? "Saving…" : "Save to site"}
            </button>
          </div>
          {previewError && <p className="text-sm text-destructive">{previewError}</p>}
          {createMut.isError && (
            <p className="text-sm text-destructive">{(createMut.error as Error).message}</p>
          )}
          {preview && (
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
              <p className="font-medium">Preview</p>
              <ul className="mt-2 grid list-none gap-1 text-xs text-muted-foreground md:grid-cols-2">
                <li>kWh (annual est.): {preview.annual_kwh_saved ?? "—"}</li>
                <li>Therms (annual est.): {preview.annual_therms_saved ?? "—"}</li>
                <li>MMBtu (annual est.): {preview.annual_mmbtu_saved ?? "—"}</li>
                <li>Cost USD (annual est.): {preview.annual_cost_saved_usd ?? "—"}</li>
                <li>Peak kW reduced: {preview.peak_kw_reduced ?? "—"}</li>
                <li>
                  Simple payback (years):{" "}
                  {preview.simple_payback_years ?? "—"}{" "}
                  <span className="text-muted-foreground">
                    (often unset until capex is modeled)
                  </span>
                </li>
                <li>Confidence: {preview.confidence_score ?? "—"}</li>
                <li>Missing inputs: {(preview.missing_inputs ?? []).join(", ") || "none"}</li>
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">{preview.notes}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

type TabId = "energy" | "metadata";

export function EnergyEngineeringPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const t = searchParams.get("tab");
  const tab: TabId = t === "metadata" || t === "energy" ? t : "energy";

  const setTab = useCallback(
    (next: TabId) => {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          if (next === "energy") {
            p.delete("tab");
          } else {
            p.set("tab", "metadata");
          }
          return p;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">Energy Engineering</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        HVAC and control layouts differ by site. Use the energy workbench for savings specs tied to this
        building&apos;s model; use equipment metadata when you need nameplate fields and topology export.
      </p>

      <div
        role="tablist"
        aria-label="Energy engineering sections"
        className="mb-6 flex flex-wrap gap-2 border-b border-border/60 pb-2"
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") {
            e.preventDefault();
            if (tab === "energy") {
              setTab("metadata");
              queueMicrotask(() => document.getElementById("tab-metadata")?.focus());
            } else {
              setTab("energy");
              queueMicrotask(() => document.getElementById("tab-energy")?.focus());
            }
          } else if (e.key === "ArrowLeft") {
            e.preventDefault();
            if (tab === "metadata") {
              setTab("energy");
              queueMicrotask(() => document.getElementById("tab-energy")?.focus());
            } else {
              setTab("metadata");
              queueMicrotask(() => document.getElementById("tab-metadata")?.focus());
            }
          } else if (e.key === "Home") {
            e.preventDefault();
            setTab("energy");
            queueMicrotask(() => document.getElementById("tab-energy")?.focus());
          } else if (e.key === "End") {
            e.preventDefault();
            setTab("metadata");
            queueMicrotask(() => document.getElementById("tab-metadata")?.focus());
          }
        }}
      >
        <button
          type="button"
          role="tab"
          id="tab-energy"
          aria-selected={tab === "energy"}
          aria-controls="panel-energy"
          tabIndex={tab === "energy" ? 0 : -1}
          onClick={() => setTab("energy")}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
            tab === "energy" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted/60"
          }`}
        >
          Energy calculations
        </button>
        <button
          type="button"
          role="tab"
          id="tab-metadata"
          aria-selected={tab === "metadata"}
          aria-controls="panel-metadata"
          tabIndex={tab === "metadata" ? 0 : -1}
          onClick={() => setTab("metadata")}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
            tab === "metadata" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted/60"
          }`}
        >
          Equipment metadata
        </button>
      </div>

      <div
        id="panel-energy"
        role="tabpanel"
        aria-labelledby="tab-energy"
        hidden={tab !== "energy"}
        tabIndex={0}
        className="outline-none"
      >
        {tab === "energy" ? <EnergyCalculationWorkbench /> : null}
      </div>
      <div
        id="panel-metadata"
        role="tabpanel"
        aria-labelledby="tab-metadata"
        hidden={tab !== "metadata"}
        tabIndex={0}
        className="outline-none"
      >
        {tab === "metadata" ? <EquipmentMetadataTab /> : null}
      </div>
    </div>
  );
}
