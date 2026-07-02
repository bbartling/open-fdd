import { useCallback, useMemo, useState } from "react";
import { apiFetch, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type FileProfile = {
  filename: string;
  profile?: {
    row_count?: number;
    delimiter?: string;
    encoding?: string;
    headers?: string[];
    timestamp_candidates?: [number, number][];
    columns?: { original_name: string; kind: string }[];
  };
  error?: string;
};

type PreviewSummary = {
  row_count?: number;
  column_names?: string[];
  sample_rows?: Record<string, unknown>[];
  time_range?: [string, string];
};

type ValidationReport = {
  warnings?: string[];
  timestamp_analysis?: {
    duplicate_local_count?: number;
    gap_count?: number;
    ambiguous_count?: number;
    inferred_interval_seconds?: number;
  };
};

type DatasetMeta = {
  id?: string;
  row_count?: number;
  time_range?: { start?: string; end?: string };
};

const TIMEZONES = ["America/Chicago", "America/New_York", "UTC"];
const MODES = [
  { id: "append", label: "Append compatible files" },
  { id: "join", label: "Join two datasets" },
  { id: "single", label: "Single file" },
];
const JOINS = [
  { id: "floor_hour", label: "Floor kW to hour + join weather" },
  { id: "as_of_previous", label: "As-of previous hour" },
  { id: "exact", label: "Exact timestamp" },
];
const FILLS = [
  { id: "none", label: "No fill" },
  { id: "forward", label: "Forward fill" },
  { id: "backward", label: "Back fill" },
  { id: "linear", label: "Linear interpolate" },
  { id: "acknowledge_only", label: "Acknowledge gaps only" },
];

import { uploadFilesForPreview } from "../lib/csvImportUpload";

type Props = {
  onPlanReady?: (sessionId: string) => void;
  onOpenInFusion?: (sessionId: string) => void;
  autoOpenFusion?: boolean;
};

export default function CsvUt3ImportPanel({ onPlanReady, onOpenInFusion, autoOpenFusion = true }: Props) {
  const [files, setFiles] = useState<FileProfile[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [mode, setMode] = useState("append");
  const [joinAlign, setJoinAlign] = useState("floor_hour");
  const [fillPolicy, setFillPolicy] = useState("forward");
  const [timezone, setTimezone] = useState("America/Chicago");
  const [datasetName, setDatasetName] = useState("school_kw_merged");
  const [tsCol, setTsCol] = useState("Date");
  const [valueCols, setValueCols] = useState("kW");
  const [wxTsCol, setWxTsCol] = useState("time_local");
  const [preview, setPreview] = useState<PreviewSummary | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [datasets, setDatasets] = useState<DatasetMeta[]>([]);
  const [savedId, setSavedId] = useState("");

  const refreshDatasets = useCallback(async () => {
    if (!hasToken()) return;
    try {
      const out = await apiFetch<{ datasets?: DatasetMeta[] }>("/api/datasets");
      setDatasets(out.datasets ?? []);
    } catch {
      /* optional */
    }
  }, []);

  const uploadPreview = useCallback(async (fileList: FileList | File[]) => {
    if (!hasToken()) {
      setError("Sign in to upload CSV files.");
      return;
    }
    setError("");
    setBusy("Uploading and profiling…");
    try {
      const out = await uploadFilesForPreview(fileList, sessionId || undefined);
      if (!out.ok && !out.session_id) throw new Error(out.error ?? "preview failed");
      if (out.errors?.length) {
        const detail = out.errors.map((e) => `${e.file ?? "?"}: ${e.error ?? "error"}`).join("; ");
        throw new Error(detail || "one or more files failed to upload");
      }
      setSessionId(out.session_id ?? "");
      setFiles(out.files ?? []);
      const profiles = out.files ?? [];
      const first = profiles[0]?.profile;
      const weather = profiles.find((f) => /meteo|weather|open_meteo/i.test(f.filename));
      const school = profiles.find((f) => /school|kw/i.test(f.filename));
      if (first?.headers?.length) {
        const tsCand = first.timestamp_candidates?.[0]?.[0];
        if (tsCand != null && first.headers[tsCand]) setTsCol(first.headers[tsCand]!);
        const vals = first.headers.filter((h) => h !== first.headers![tsCand ?? 0]).slice(0, 3);
        if (vals.length) setValueCols(vals.join(", "));
      }
      if (school?.profile?.headers?.includes("Date")) setTsCol("Date");
      if (weather?.profile?.headers?.includes("time_local")) setWxTsCol("time_local");
      else if (weather?.profile?.headers?.includes("timezone")) {
        setWxTsCol(weather.profile.headers.find((h) => h === "time_local") ?? "time_local");
      }
      const schoolCount = profiles.filter((f) => /school|kw/i.test(f.filename)).length;
      if (weather && schoolCount >= 1) {
        setMode("join");
        setJoinAlign("floor_hour");
        setDatasetName("school_kw_merged");
      } else if (schoolCount >= 2) {
        setMode("append");
        setDatasetName("school_kw_merged");
      }
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, [sessionId]);

  const buildPlan = useCallback(async () => {
    if (!sessionId) {
      setError("Upload files first.");
      return;
    }
    setBusy("Building plan…");
    setError("");
    try {
      const fileMappings =
        mode === "join" && files.length >= 2
          ? (() => {
              const weatherFile =
                files.find((f) => /meteo|weather|open_meteo/i.test(f.filename)) ?? files[files.length - 1]!;
              const schoolFiles = files.filter(
                (f) => f !== weatherFile && !/meteo|weather|open_meteo/i.test(f.filename),
              );
              const schools = schoolFiles.length ? schoolFiles : [files[0]!];
              return [
                ...schools.map((f) => ({
                  filename: f.filename,
                  timestamp_column: f.profile?.headers?.includes("Date") ? "Date" : tsCol,
                  timezone,
                  value_columns: valueCols.split(",").map((s) => s.trim()).filter(Boolean),
                })),
                {
                  filename: weatherFile.filename,
                  timestamp_column: weatherFile.profile?.headers?.includes("time_local") ? "time_local" : wxTsCol,
                  timezone,
                  value_columns:
                    weatherFile.profile?.headers
                      ?.filter((h) => h !== "time_local" && h !== "timezone" && h !== "Date")
                      .slice(0, 12) ?? [],
                },
              ];
            })()
          : files
              .filter((f) => mode !== "append" || !/meteo|weather|open_meteo/i.test(f.filename))
              .map((f) => ({
                filename: f.filename,
                timestamp_column: f.profile?.headers?.includes("Date") ? "Date" : tsCol,
                timezone,
                value_columns: valueCols.split(",").map((s) => s.trim()).filter(Boolean),
              }));

      const out = await apiFetch<{
        ok?: boolean;
        preview?: PreviewSummary;
        validation_report?: ValidationReport;
        error?: string;
      }>("/api/csv/import/plan", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          plan: {
            mode,
            output_dataset_name: datasetName,
            ambiguous_policy: "first",
            fill_policy: fillPolicy,
            join_alignment: joinAlign,
            files: fileMappings,
          },
        }),
      });
      if (!out.ok) throw new Error(out.error ?? "plan failed");
      setPreview(out.preview ?? null);
      setValidation(out.validation_report ?? null);
      if (sessionId && onPlanReady) onPlanReady(sessionId);
      if (sessionId && autoOpenFusion && onOpenInFusion) onOpenInFusion(sessionId);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, [sessionId, mode, files, tsCol, wxTsCol, timezone, valueCols, datasetName, fillPolicy, joinAlign, onPlanReady, onOpenInFusion, autoOpenFusion]);

  const executeSave = useCallback(async () => {
    if (!sessionId) return;
    setBusy("Saving Arrow/Feather dataset…");
    setError("");
    try {
      const out = await apiFetch<{ ok?: boolean; dataset?: { id?: string }; error?: string }>(
        "/api/csv/import/execute",
        {
          method: "POST",
          body: JSON.stringify({ session_id: sessionId, confirm: true }),
        },
      );
      if (!out.ok) throw new Error(out.error ?? "save failed");
      setSavedId(out.dataset?.id ?? datasetName);
      await refreshDatasets();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, [sessionId, datasetName, refreshDatasets]);

  const deleteDataset = useCallback(
    async (id: string) => {
      if (!hasToken() || !confirm(`Delete dataset ${id}?`)) return;
      await apiFetch("/api/datasets", {
        method: "DELETE",
        body: JSON.stringify({ dataset_id: id }),
      });
      await refreshDatasets();
    },
    [refreshDatasets],
  );

  const previewRows = useMemo(() => preview?.sample_rows?.slice(0, 50) ?? [], [preview]);

  return (
    <section className="card csv-ut3-panel">
      <h2>UT3 CSV Import (Rust server)</h2>
      <p className="muted">
        Upload → profile → append/join → validate → preview → save to Arrow store. No client-side merge for
        finalized datasets.
      </p>

      <div
        className="drop-zone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          void uploadPreview(e.dataTransfer.files);
        }}
      >
        <input
          type="file"
          accept=".csv,text/csv"
          multiple
          onChange={(e) => e.target.files && void uploadPreview(e.target.files)}
        />
        <span>Drop CSV files or click to browse</span>
      </div>

      {sessionId ? (
        <p className="ok csv-session-id-line">
          <strong>Rust import session:</strong> <code>{sessionId}</code>
          {" · "}
          <a href={`/csv?session=${encodeURIComponent(sessionId)}`}>fusion preview link</a>
          {" · "}
          shown after upload — agent uses this ID to reload your cleaned merge
        </p>
      ) : null}

      {files.length > 0 && (
        <div className="csv-ut3-files">
          <h3>File profiles</h3>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>File</th>
                <th>Rows</th>
                <th>Delimiter</th>
                <th>Encoding</th>
                <th>Timestamp candidates</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.filename}>
                  <td>{f.filename}</td>
                  <td>{f.error ? "—" : f.profile?.row_count}</td>
                  <td>{f.profile?.delimiter}</td>
                  <td>{f.profile?.encoding}</td>
                  <td>
                    {f.profile?.timestamp_candidates
                      ?.slice(0, 2)
                      .map(([i, score]) => `${f.profile?.headers?.[i] ?? i} (${(score * 100).toFixed(0)}%)`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {mode === "join" && files.filter((f) => !/meteo|weather|open_meteo/i.test(f.filename)).length > 1 && (
        <p className="muted csv-ut3-hint">
          Join mode appends all school kW files by timestamp, then joins hourly weather using floor-hour
          alignment.
        </p>
      )}
      {mode === "append" && files.some((f) => /meteo|weather/i.test(f.filename)) && (
        <p className="muted csv-ut3-hint">
          Append mode skips weather files. Use Join to add Open-Meteo columns, or remove weather from the upload for
          append-only.
        </p>
      )}

      <div className="csv-ut3-controls grid-2">
        <label>
          Mode
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Timezone
          <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </select>
        </label>
        <label>
          Timestamp column
          <input value={tsCol} onChange={(e) => setTsCol(e.target.value)} />
        </label>
        <label>
          Value columns (comma)
          <input value={valueCols} onChange={(e) => setValueCols(e.target.value)} />
        </label>
        {mode === "join" && (
          <label>
            Weather timestamp column
            <input value={wxTsCol} onChange={(e) => setWxTsCol(e.target.value)} />
          </label>
        )}
        <label>
          Join alignment
          <select value={joinAlign} onChange={(e) => setJoinAlign(e.target.value)} disabled={mode !== "join"}>
            {JOINS.map((j) => (
              <option key={j.id} value={j.id}>
                {j.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Fill policy
          <select value={fillPolicy} onChange={(e) => setFillPolicy(e.target.value)}>
            {FILLS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Output dataset name
          <input value={datasetName} onChange={(e) => setDatasetName(e.target.value)} />
        </label>
      </div>

      <div className="toolbar">
        <button type="button" disabled={!!busy || !sessionId} onClick={() => void buildPlan()}>
          Preview plan
        </button>
        {preview && sessionId && onOpenInFusion ? (
          <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => onOpenInFusion(sessionId)}>
            Open in fusion preview
          </button>
        ) : null}
        <button type="button" disabled={!!busy || !preview} onClick={() => void executeSave()}>
          Save to Arrow store
        </button>
        <button type="button" onClick={() => void refreshDatasets()}>
          Refresh datasets
        </button>
      </div>

      {validation && (
        <div className="csv-ut3-validation">
          <h3>Validation report</h3>
          <ul>
            {(validation.warnings ?? []).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          {validation.timestamp_analysis && (
            <p className="muted">
              DST duplicates: {validation.timestamp_analysis.duplicate_local_count ?? 0} · gaps:{" "}
              {validation.timestamp_analysis.gap_count ?? 0} · interval:{" "}
              {validation.timestamp_analysis.inferred_interval_seconds ?? "—"}s
            </p>
          )}
        </div>
      )}

      {preview && (
        <div className="csv-ut3-preview">
          <h3>
            Preview ({preview.row_count?.toLocaleString()} rows) — showing {previewRows.length}
          </h3>
          <div className="preview-scroll">
            <table className="data-table compact">
              <thead>
                <tr>
                  {(preview.column_names ?? Object.keys(previewRows[0] ?? {})).slice(0, 12).map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) => (
                  <tr key={i}>
                    {(preview.column_names ?? Object.keys(row)).slice(0, 12).map((c) => (
                      <td key={c}>{String(row[c] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {savedId && (
        <p className="ok-banner">
          Saved dataset <code>{savedId}</code>. Map columns in Haystack model or run FDD rules against historian /
          dataset SQL.
        </p>
      )}

      {datasets.length > 0 && (
        <div className="csv-ut3-datasets">
          <h3>Saved datasets</h3>
          <ul>
            {datasets.map((d) => (
              <li key={d.id}>
                {d.id} — {d.row_count?.toLocaleString()} rows
                <button type="button" className="linkish" onClick={() => d.id && void deleteDataset(d.id)}>
                  delete
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {busy && <p className="muted">{busy}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
