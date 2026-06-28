import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch, apiUploadRaw, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  analyzeQualityLocal,
  datasetsToCsv,
  downloadCsv,
  fileToDataset,
  idsFromFilename,
  mergeDatasets,
  numericColumns,
  suggestMergeKey,
  splitCsvHorizontal,
  splitCsvVertical,
  type CsvDataset,
  type MergeMode,
} from "../lib/csvWorkbench";
import CsvFusionWiresheet from "../wiresheet/CsvFusionWiresheet";
import CsvUt3ImportPanel from "../components/CsvUt3ImportPanel";
import CsvWorkflowGuide from "../components/CsvWorkflowGuide";
import CsvDataAssistant from "../components/CsvDataAssistant";
import CsvAgentSessionPanel from "../components/CsvAgentSessionPanel";
import {
  datasetFromFusionPreview,
  fetchAgentSessionFusionPreview,
  saveAgentSessionToArrow,
  type FusionPreviewResponse,
} from "../lib/csvAgentSession";

type JobStatus = { ok?: boolean; job_id?: string; rows_committed?: number };
type ModelPreview = {
  ok?: boolean;
  site_id?: string;
  equipment_id?: string;
  source_id?: string;
  display_name?: string;
  point_count?: number;
  points?: { header: string; fdd_input: string; auto_fdd_input?: string; mapped_override?: boolean }[];
};
type Recipe = {
  id: string;
  name: string;
  merge_key: string;
  merge_mode: MergeMode;
  filenames: string[];
};

const FDD_INPUTS = ["oa_t", "oa_h", "sat", "sat_sp", "duct_t", "zn_t", "fan_cmd", "occ", "duct_static", ""];

export default function CsvWorkbenchPage() {
  const [datasets, setDatasets] = useState<CsvDataset[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [mergeKey, setMergeKey] = useState("Date");
  const [mergeMode, setMergeMode] = useState<MergeMode>("inner");
  const [modelPreview, setModelPreview] = useState<ModelPreview | null>(null);
  const [columnMappings, setColumnMappings] = useState<Record<string, string>>({});
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [recipeName, setRecipeName] = useState("");
  const [splitCol, setSplitCol] = useState(5);
  const [splitRows, setSplitRows] = useState(500);
  const [ruleInput, setRuleInput] = useState("oa_t");
  const [ruleOp, setRuleOp] = useState(">");
  const [ruleThreshold, setRuleThreshold] = useState("75");
  const [purgeConfirm, setPurgeConfirm] = useState("");
  const [ut3SessionId, setUt3SessionId] = useState("");
  const [agentMeta, setAgentMeta] = useState<FusionPreviewResponse | null>(null);

  const loadAgentSession = useCallback((ds: CsvDataset, sessionId: string, meta: FusionPreviewResponse) => {
    setUt3SessionId(sessionId);
    setAgentMeta(meta);
    setDatasets([ds]);
    setMergeKey(ds.timestampColumn ?? "ts_local");
    setMergeMode("append");
    setStatus(
      `Agent session loaded — ${meta.row_count?.toLocaleString() ?? ds.rowCount.toLocaleString()} rows. Review preview, then Save to Arrow.`,
    );
    setError("");
  }, []);

  const openFusionFromSession = useCallback(
    async (sessionId: string) => {
      if (!hasToken()) {
        setError("Sign in to load sessions.");
        return;
      }
      setBusy("agent-load");
      try {
        const data = await fetchAgentSessionFusionPreview(sessionId);
        if (!data.ok) throw new Error(data.error ?? "load failed");
        loadAgentSession(datasetFromFusionPreview(data, sessionId), sessionId, data);
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setBusy("");
      }
    },
    [loadAgentSession],
  );

  const commitFilename = useMemo(() => {
    if (datasets.length === 1) return datasets[0].name;
    return "openfdd-merged.csv";
  }, [datasets]);

  const merged = useMemo(() => {
    if (!datasets.length) return null;
    try {
      return mergeDatasets(datasets, mergeKey, mergeMode);
    } catch {
      return null;
    }
  }, [datasets, mergeKey, mergeMode]);

  const mergeError = useMemo(() => {
    if (!datasets.length || datasets.length === 1) return "";
    try {
      mergeDatasets(datasets, mergeKey, mergeMode);
      return "";
    } catch (e) {
      return formatApiError(e);
    }
  }, [datasets, mergeKey, mergeMode]);

  const quality = useMemo(() => {
    if (!merged?.columns.length) return null;
    return analyzeQualityLocal(merged.columns, merged.rows);
  }, [merged]);

  const numericCols = useMemo(
    () => (merged ? numericColumns(merged.columns, merged.rows) : []),
    [merged],
  );

  const loadRecipes = useCallback(async () => {
    if (!hasToken()) return;
    try {
      const out = await apiFetch<{ recipes?: Recipe[] }>("/api/csv-workbench/recipes");
      setRecipes(out.recipes ?? []);
    } catch {
      /* optional */
    }
  }, []);

  const refreshModelPreview = useCallback(async () => {
    if (!merged?.columns.length) {
      setModelPreview(null);
      return;
    }
    const ids = idsFromFilename(commitFilename);
    try {
      const out = await apiFetch<ModelPreview>("/api/csv-workbench/preview", {
        method: "POST",
        body: JSON.stringify({
          source_filename: commitFilename,
          headers: merged.columns,
        }),
      });
      setModelPreview(out);
      if (hasToken()) {
        const maps = await apiFetch<{ mappings?: Record<string, string> }>(
          `/api/csv-workbench/column-mappings?source_id=${encodeURIComponent(ids.sourceId)}`,
        );
        setColumnMappings(maps.mappings ?? {});
      }
    } catch (e) {
      setModelPreview({
        ok: true,
        ...ids,
        display_name: commitFilename,
        point_count: merged.columns.length - 1,
        points: merged.columns.slice(1).map((h) => ({ header: h, fdd_input: h })),
      });
      void e;
    }
  }, [merged, commitFilename]);

  useEffect(() => {
    void loadRecipes();
  }, [loadRecipes]);

  useEffect(() => {
    void refreshModelPreview();
  }, [refreshModelPreview]);

  const ingestFiles = useCallback(async (files: FileList | File[]) => {
    setError("");
    const list = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".csv") || f.type.includes("csv"));
    if (!list.length) {
      setError("Drop or pick one or more .csv files.");
      return;
    }
    setBusy("parse");
    try {
      const added: CsvDataset[] = [];
      for (const file of list) {
        added.push(fileToDataset(file, await file.text()));
      }
      setDatasets((prev) => {
        const next = [...prev, ...added];
        setMergeKey(suggestMergeKey(next));
        const allHaveDate = next.every((d) => d.columns.includes("Date"));
        const hasWeather = next.some((d) => /meteo|weather|open_meteo/i.test(d.name));
        if (next.length > 1 && allHaveDate && !hasWeather) {
          setMergeMode("append");
        }
        return next;
      });
      setStatus(`Loaded ${added.length} file(s).`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, []);

  async function saveColumnMappings() {
    if (!modelPreview?.source_id) return;
    setBusy("map");
    try {
      await apiFetch("/api/csv-workbench/column-mappings", {
        method: "PUT",
        body: JSON.stringify({ source_id: modelPreview.source_id, mappings: columnMappings }),
      });
      setStatus("Column → FDD input mappings saved for this source.");
      await refreshModelPreview();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function saveRecipe() {
    if (!recipeName.trim()) {
      setError("Recipe name required.");
      return;
    }
    const id = recipeName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
    setBusy("recipe");
    try {
      await apiFetch("/api/csv-workbench/recipes", {
        method: "POST",
        body: JSON.stringify({
          id,
          name: recipeName,
          merge_key: mergeKey,
          merge_mode: mergeMode,
          filenames: datasets.map((d) => d.name),
        }),
      });
      setStatus(`Recipe "${recipeName}" saved.`);
      setRecipeName("");
      await loadRecipes();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  function applyRecipe(recipe: Recipe) {
    setMergeKey(recipe.merge_key);
    setMergeMode(recipe.merge_mode);
    setStatus(`Applied recipe "${recipe.name}" — load files: ${recipe.filenames.join(", ")}`);
  }

  function splitSelectedVertical(ds: CsvDataset) {
    const { left, right } = splitCsvVertical(ds.fullText, splitCol);
    const leftDs = fileToDataset(new File([left], `${ds.name.replace(/\.csv$/i, "")}-left.csv`, { type: "text/csv" }), left);
    const rightDs = fileToDataset(new File([right], `${ds.name.replace(/\.csv$/i, "")}-right.csv`, { type: "text/csv" }), right);
    setDatasets((prev) => [...prev.filter((d) => d.id !== ds.id), leftDs, rightDs]);
    setStatus(`Split ${ds.name} vertically after column ${splitCol}.`);
  }

  function splitSelectedHorizontal(ds: CsvDataset) {
    const { first, second } = splitCsvHorizontal(ds.fullText, splitRows);
    const a = fileToDataset(new File([first], `${ds.name.replace(/\.csv$/i, "")}-part-a.csv`, { type: "text/csv" }), first);
    const b = fileToDataset(new File([second], `${ds.name.replace(/\.csv$/i, "")}-part-b.csv`, { type: "text/csv" }), second);
    setDatasets((prev) => [...prev.filter((d) => d.id !== ds.id), a, b]);
    setStatus(`Split ${ds.name} horizontally after ${splitRows} data rows.`);
  }

  async function commitToHistorian() {
    if (!datasets.length || !merged) {
      setError("Load a CSV file first.");
      return;
    }
    if (!hasToken()) {
      setError("Sign in as integrator to commit CSV to the historian.");
      return;
    }
    if (quality && !quality.readyToCommit) {
      setError("Resolve duplicate timestamps before commit (or review data quality panel).");
      return;
    }
    setBusy("commit");
    setError("");
    try {
      if (Object.keys(columnMappings).length) {
        await saveColumnMappings();
      }
      const csvBody = datasetsToCsv(merged.columns, merged.rows);
      const created = await apiFetch<JobStatus>("/api/import/jobs", {
        method: "POST",
        body: JSON.stringify({ source_filename: commitFilename }),
      });
      if (!created.job_id) throw new Error("Could not create import job");
      await apiUploadRaw(`/api/import/jobs/${encodeURIComponent(created.job_id)}/upload`, csvBody, "text/csv");
      await apiFetch(`/api/import/jobs/${encodeURIComponent(created.job_id)}/preview`);
      const committed = await apiFetch<JobStatus>(
        `/api/import/jobs/${encodeURIComponent(created.job_id)}/commit`,
        { method: "POST", body: "{}" },
      );
      setStatus(
        `Historian commit OK — ${committed.rows_committed ?? 0} rows · model ${modelPreview?.site_id ?? "auto"}.`,
      );
      window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function draftRule() {
    if (!hasToken() || !modelPreview?.equipment_id) {
      setError("Sign in and load CSV to draft a rule.");
      return;
    }
    setBusy("rule");
    try {
      const out = await apiFetch<{ ok?: boolean; rule_id?: string }>("/api/csv-workbench/draft-rule", {
        method: "POST",
        body: JSON.stringify({
          equipment_id: modelPreview.equipment_id,
          fdd_input: ruleInput,
          operator: ruleOp,
          threshold: Number.parseFloat(ruleThreshold),
          name: `CSV rule — ${ruleInput} ${ruleOp} ${ruleThreshold}`,
        }),
      });
      setStatus(`Draft FDD rule saved (${out.rule_id ?? "csv_workbench_rule"}) — approve in FDD wires.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function purgeSource() {
    if (!modelPreview?.source_id || purgeConfirm !== "PURGE HISTORIAN DATA") {
      setError('Type PURGE HISTORIAN DATA to confirm source-scoped purge.');
      return;
    }
    setBusy("purge");
    try {
      const preview = await apiFetch<{ historian_rows_matched?: number; model_entities_matched?: number }>(
        "/api/csv-workbench/purge-source/preview",
        { method: "POST", body: JSON.stringify({ source_id: modelPreview.source_id }) },
      );
      const out = await apiFetch<{ ok?: boolean }>("/api/csv-workbench/purge-source/execute", {
        method: "POST",
        body: JSON.stringify({ source_id: modelPreview.source_id, confirm: purgeConfirm }),
      });
      if (!out.ok) throw new Error("Purge failed");
      setStatus(
        `Purged source ${modelPreview.source_id} — ${preview.historian_rows_matched ?? 0} historian rows, ${preview.model_entities_matched ?? 0} model entities.`,
      );
      setPurgeConfirm("");
      window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function createRcxReport() {
    if (!hasToken()) {
      setError("Sign in to generate RCx PDF reports.");
      return;
    }
    setBusy("report");
    try {
      const draft = await apiFetch<{ report_id?: string }>("/api/reports/draft", {
        method: "POST",
        body: JSON.stringify({
          template_id: "rcx-universal-3",
          title: "RCx Universal 3 — CSV Workbench Report",
        }),
      });
      if (!draft.report_id) throw new Error("Report draft failed");
      await apiFetch(`/api/reports/${draft.report_id}/render/pdf`, { method: "POST" });
      setStatus(`Report ${draft.report_id} — open Reports tab to download PDF.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="page page-wide csv-workbench-page">
      <PageHeader
        title="CSV Fusion / UT3 Import"
        subtitle="Server-side Rust ingest (append, join, DST-aware timestamps, Arrow save) or client fusion wiresheet below."
      />

      <CsvWorkflowGuide variant="ut3" />
      <CsvUt3ImportPanel
        onPlanReady={(sid) => {
          setUt3SessionId(sid);
          setStatus(`UT3 plan ready (session ${sid}). Open in fusion preview when ready.`);
        }}
        onOpenInFusion={(sid) => void openFusionFromSession(sid)}
      />

      <CsvAgentSessionPanel
        activeSessionId={ut3SessionId}
        suggestedSessionId={ut3SessionId}
        onLoaded={loadAgentSession}
        onSaved={({ plotUrl, modelUrl, datasetId, siteId }) => {
          setStatus(
            `Arrow dataset "${datasetId ?? "saved"}" synced to historian${siteId ? ` (${siteId})` : ""}. Open Plot tab to chart kW + weather.`,
          );
          if (plotUrl || modelUrl) {
            setAgentMeta((m) => m ?? { ok: true });
          }
        }}
      />

      <CsvWorkflowGuide variant="fusion" />
      <CsvDataAssistant mergeError={mergeError} fileCount={datasets.length} />

      <hr className="section-divider" />

      {error ? <p className="error">{error}</p> : null}
      {mergeError ? <p className="error">{mergeError}</p> : null}
      {status ? <p className="ok">{status}</p> : null}

      <div
        className={`csv-drop-zone${dragOver ? " csv-drop-zone-active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void ingestFiles(e.dataTransfer.files);
        }}
      >
        <p className="csv-drop-title">Drop CSV files here</p>
        <p className="muted">Any wide-format building CSV — site/equip/source derived from filename</p>
        <label className="primary-btn csv-drop-btn">
          {busy === "parse" ? "Parsing…" : "Choose files"}
          <input
            type="file"
            accept=".csv,text/csv"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files?.length) void ingestFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {datasets.length ? (
        <>
          <section className="panel csv-fusion-panel">
            <h3 className="panel-title">Fusion wiresheet</h3>
            <p className="muted">
              Each uploaded file is a source node. Choose join or append, then commit the merged output to the historian.
            </p>
            <CsvFusionWiresheet
              datasets={datasets}
              mergeKey={mergeKey}
              mergeMode={mergeMode}
              onMergeKeyChange={setMergeKey}
              onMergeModeChange={setMergeMode}
            />
            <div className="csv-merge-controls form-grid">
              <label className="field">
                <span className="field-label">Timestamp column</span>
                <input value={mergeKey} onChange={(e) => setMergeKey(e.target.value)} placeholder="Date, timestamp, …" />
              </label>
              <label className="field">
                <span className="field-label">Merge mode</span>
                <select value={mergeMode} onChange={(e) => setMergeMode(e.target.value as MergeMode)}>
                  <option value="append">Append rows (stack school-year files)</option>
                  <option value="inner">Join on timestamp (same column name in all files)</option>
                </select>
              </label>
            </div>
          </section>

          {merged && merged.columns.length ? (
            <section className="panel csv-preview-panel csv-preview-panel--primary">
              <h3 className="panel-title">Merged preview ({merged.rowCount.toLocaleString()} rows)</h3>
              <p className="muted">
                {mergeMode === "append" ? "Appended" : "Joined"} on <strong>{mergeKey}</strong> — first 12 rows
                shown. Export or commit when this looks correct.
              </p>
              <div className="table-wrap csv-preview-table">
                <table>
                  <thead>
                    <tr>
                      {merged.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {merged.rows.slice(0, 12).map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          <section className="panel">
            <h3 className="panel-title">Loaded datasets ({datasets.length})</h3>
            <ul className="csv-dataset-list">
              {datasets.map((ds) => (
                <li key={ds.id}>
                  <strong>{ds.name}</strong>
                  <span className="muted">
                    {" "}
                    — {ds.rowCount.toLocaleString()} rows · ts: {ds.timestampColumn ?? "auto"} · {ds.columns.length} cols
                  </span>
                  <button type="button" className="linkish-btn" onClick={() => splitSelectedVertical(ds)}>
                    Split vertical
                  </button>
                  <button type="button" className="linkish-btn" onClick={() => splitSelectedHorizontal(ds)}>
                    Split horizontal
                  </button>
                  <button type="button" className="linkish-btn" onClick={() => setDatasets((p) => p.filter((d) => d.id !== ds.id))}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="csv-recipes-header">
              <div>
                <h3 className="panel-title">Saved merge recipes</h3>
                <p className="muted">Store join/append settings for repeat uploads — AI can also generate these from your file set.</p>
              </div>
              <div className="csv-recipes-save">
                <input
                  value={recipeName}
                  onChange={(e) => setRecipeName(e.target.value)}
                  placeholder="Recipe name (e.g. weekly-trend-merge)"
                  aria-label="Recipe name"
                />
                <button type="button" className="primary-btn" disabled={!datasets.length || !!busy} onClick={() => void saveRecipe()}>
                  Save recipe
                </button>
              </div>
            </div>
            {recipes.length ? (
              <div className="csv-recipe-cards">
                {recipes.map((r) => (
                  <article key={r.id} className="csv-recipe-card">
                    <h4>{r.name}</h4>
                    <p className="csv-recipe-card__meta">
                      <span className="chip">{r.merge_mode === "append" ? "Append" : "Join"}</span>
                      <span className="muted">on {r.merge_key}</span>
                    </p>
                    <p className="muted csv-recipe-card__files">{r.filenames.join(" · ")}</p>
                    <button type="button" className="secondary-btn" onClick={() => applyRecipe(r)}>
                      Apply settings
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted csv-recipes-empty">No saved recipes — configure merge above and save, or import via AI commissioning JSON on Model tab.</p>
            )}
          </section>

          <section className="panel">
            <h3 className="panel-title">Finish — commit or export</h3>
            <p className="muted">
              {ut3SessionId
                ? "This preview came from a UT3/agent session — use Save to Arrow (session) above or below. Client commit uploads the preview grid to the historian."
                : "Commit writes the merged CSV to the Arrow historian and Haystack model. Export downloads a copy for inspection."}
            </p>
            <div className="toolbar">
              {ut3SessionId ? (
                <button
                  type="button"
                  className="primary-btn"
                  disabled={!!busy}
                  onClick={async () => {
                    setBusy("arrow");
                    try {
                      const out = await saveAgentSessionToArrow(ut3SessionId);
                      if (!out.ok) throw new Error(out.error ?? "save failed");
                      setStatus(`Arrow dataset saved (${agentMeta?.dataset_name ?? ut3SessionId}).`);
                    } catch (e) {
                      setError(formatApiError(e));
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  {busy === "arrow" ? "Saving…" : "Save to Arrow store (session)"}
                </button>
              ) : null}
              <button
                type="button"
                className={ut3SessionId ? "secondary-btn" : "primary-btn"}
                disabled={!!busy || !merged}
                onClick={() => void commitToHistorian()}
              >
                {busy === "commit" ? "Committing…" : "Commit → historian + model"}
              </button>
              <button
                type="button"
                className="secondary-btn"
                disabled={!merged}
                onClick={() => merged && downloadCsv("openfdd-merged.csv", merged.columns, merged.rows)}
              >
                Export merged CSV
              </button>
              <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void createRcxReport()}>
                Draft RCx PDF
              </button>
              {numericCols.length ? (
                <a className="secondary-btn" href="/plot">
                  Open in Plots
                </a>
              ) : null}
              <button type="button" className="linkish-btn" onClick={() => setDatasets([])}>
                Clear all
              </button>
            </div>
          </section>

          <section className="panel">
            <h3 className="panel-title">Advanced — split a file</h3>
            <p className="muted">
              Optional: break one wide or long CSV into two files before merge. Select split settings, then use Split on
              a file in the list below.
            </p>
            <div className="form-grid">
              <label className="field">
                <span className="field-label">Vertical split after col #</span>
                <input type="number" min={1} value={splitCol} onChange={(e) => setSplitCol(Number(e.target.value))} />
              </label>
              <label className="field">
                <span className="field-label">Horizontal split after rows</span>
                <input type="number" min={1} value={splitRows} onChange={(e) => setSplitRows(Number(e.target.value))} />
              </label>
            </div>
          </section>
        </>
      ) : null}

      {modelPreview?.ok ? (
        <section className="panel">
          <h3 className="panel-title">Pre-commit model preview</h3>
          <p className="muted">
            From <strong>{commitFilename}</strong> — no manual site/equip fields.
          </p>
          <ul className="csv-meta-list">
            <li>
              <strong>Site:</strong> {modelPreview.site_id}
            </li>
            <li>
              <strong>Equipment:</strong> {modelPreview.equipment_id}
            </li>
            <li>
              <strong>Source:</strong> {modelPreview.source_id}
            </li>
            <li>
              <strong>Points:</strong> {modelPreview.point_count}
            </li>
          </ul>
        </section>
      ) : null}

      {modelPreview?.points?.length ? (
        <section className="panel">
          <h3 className="panel-title">Column → FDD input mapper</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>CSV column</th>
                  <th>Auto</th>
                  <th>FDD input</th>
                </tr>
              </thead>
              <tbody>
                {modelPreview.points.map((pt) => (
                  <tr key={pt.header}>
                    <td>{pt.header}</td>
                    <td className="muted">{pt.auto_fdd_input ?? "—"}</td>
                    <td>
                      <select
                        value={columnMappings[pt.header] ?? pt.fdd_input}
                        onChange={(e) =>
                          setColumnMappings((m) => ({
                            ...m,
                            [pt.header]: e.target.value,
                          }))
                        }
                      >
                        {FDD_INPUTS.filter(Boolean).map((id) => (
                          <option key={id} value={id}>
                            {id}
                          </option>
                        ))}
                        <option value={pt.fdd_input}>{pt.fdd_input} (column slug)</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void saveColumnMappings()}>
            Save mappings for source
          </button>
        </section>
      ) : null}

      {quality ? (
        <section className="panel">
          <h3 className="panel-title">Data quality</h3>
          <p className={quality.readyToCommit ? "ok" : "error"}>
            {quality.readyToCommit ? "Ready to commit" : "Review warnings before commit"}
          </p>
          <ul>
            {quality.warnings.map((w) => (
              <li key={w.code + w.message}>
                [{w.severity}] {w.message}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {modelPreview?.equipment_id ? (
        <section className="panel">
          <h3 className="panel-title">Post-import rule wizard (draft)</h3>
          <div className="form-grid">
            <label className="field">
              <span className="field-label">FDD input</span>
              <select value={ruleInput} onChange={(e) => setRuleInput(e.target.value)}>
                {FDD_INPUTS.filter(Boolean).map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Operator</span>
              <select value={ruleOp} onChange={(e) => setRuleOp(e.target.value)}>
                <option value=">">&gt;</option>
                <option value="<">&lt;</option>
                <option value=">=">&gt;=</option>
                <option value="<=">&lt;=</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">Threshold</span>
              <input value={ruleThreshold} onChange={(e) => setRuleThreshold(e.target.value)} />
            </label>
          </div>
          <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void draftRule()}>
            Save draft SQL rule
          </button>
        </section>
      ) : null}

      {modelPreview?.source_id ? (
        <section className="panel">
          <h3 className="panel-title">Purge by CSV source</h3>
          <p className="muted">Removes historian rows and model entities for {modelPreview.source_id} only.</p>
          <label className="field">
            <span className="field-label">Type PURGE HISTORIAN DATA to confirm</span>
            <input value={purgeConfirm} onChange={(e) => setPurgeConfirm(e.target.value)} />
          </label>
          <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void purgeSource()}>
            Purge this source
          </button>
        </section>
      ) : null}
    </div>
  );
}
