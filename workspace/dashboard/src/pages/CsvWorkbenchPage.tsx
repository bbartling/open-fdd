import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import CsvMappingPanel from "../components/CsvMappingPanel";
import CsvSessionSidecart from "../components/CsvSessionSidecart";
import Spinner from "../components/Spinner";
import { hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  uploadFilesForPreview,
  type CsvPreviewFileProfile,
} from "../lib/csvImportUpload";
import {
  datasetFromFusionPreview,
  fetchAgentSessionFusionPreview,
  saveAgentSessionToArrow,
} from "../lib/csvAgentSession";
import {
  inspectZipPackage,
  planZipPackage,
  summarizeZipManifest,
  type ZipPackageManifest,
} from "../lib/csvZipPackage";

type UploadCard = CsvPreviewFileProfile & { sessionId?: string };

export default function CsvWorkbenchPage() {
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [uploadCards, setUploadCards] = useState<UploadCard[]>([]);
  const [showMapping, setShowMapping] = useState(false);
  const [zipManifest, setZipManifest] = useState<ZipPackageManifest | null>(null);

  const availableColumns = useMemo(() => {
    const cols = new Set<string>();
    for (const card of uploadCards) {
      for (const h of card.profile?.headers ?? []) {
        if (h.trim()) cols.add(h.trim());
      }
    }
    return Array.from(cols);
  }, [uploadCards]);

  const ingestCsvFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!hasToken()) {
        setError("Sign in to upload CSV files.");
        return;
      }
      const list = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".csv"));
      if (!list.length) {
        setError("Choose one or more .csv files (or a .zip package).");
        return;
      }
      setError("");
      setBusy("upload");
      try {
        const res = await uploadFilesForPreview(list, sessionId || undefined);
        if (!res.ok && res.error) throw new Error(res.error);
        const sid = res.session_id ?? sessionId;
        if (sid) setSessionId(sid);
        const cards: UploadCard[] = (res.files ?? []).map((f) => ({ ...f, sessionId: sid }));
        setUploadCards((prev) => [...cards, ...prev]);
        const rejected = cards.filter((c) => c.error).length;
        const ok = cards.length - rejected;
        setStatus(
          `Uploaded ${ok} file(s)${rejected ? ` · ${rejected} rejected` : ""}${sid ? ` · session ${sid}` : ""}`,
        );
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setBusy("");
      }
    },
    [sessionId],
  );

  const ingestZipFile = useCallback(async (file: File) => {
    if (!hasToken()) {
      setError("Sign in to upload ZIP packages.");
      return;
    }
    setError("");
    setBusy("zip");
    try {
      const manifest = await inspectZipPackage(file);
      if (!manifest.ok && manifest.error) throw new Error(manifest.error);
      setZipManifest(manifest);
      setStatus(
        `ZIP inspected · ${summarizeZipManifest(manifest)}${
          manifest.package_id ? ` · package ${manifest.package_id}` : ""
        }`,
      );
    } catch (e) {
      setError(formatApiError(e));
      setZipManifest(null);
    } finally {
      setBusy("");
    }
  }, []);

  const ingestFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      const zips = list.filter((f) => f.name.toLowerCase().endsWith(".zip"));
      const csvs = list.filter((f) => f.name.toLowerCase().endsWith(".csv"));
      if (zips.length > 1) {
        setError("Upload one ZIP package at a time.");
        return;
      }
      if (zips.length === 1) {
        if (csvs.length) {
          setError("Upload either a ZIP package or CSV files, not both at once.");
          return;
        }
        await ingestZipFile(zips[0]!);
        return;
      }
      await ingestCsvFiles(list);
    },
    [ingestCsvFiles, ingestZipFile],
  );

  async function proceedZipToMapping() {
    if (!zipManifest?.package_id) {
      setError("Inspect a ZIP package first.");
      return;
    }
    if (!hasToken()) {
      setError("Sign in to plan a ZIP package.");
      return;
    }
    setBusy("plan");
    setError("");
    try {
      const planned = await planZipPackage(zipManifest.package_id);
      if (!planned.ok && planned.error) throw new Error(planned.error);
      const sid = planned.session_id ?? "";
      if (sid) setSessionId(sid);
      const cards: UploadCard[] = (planned.files ?? []).map((f) => ({
        filename: f.filename ?? f.package_path ?? "file.csv",
        profile: f.profile,
        error: f.error,
        sessionId: sid,
      }));
      setUploadCards(cards);
      setShowMapping(true);
      const mapNote = planned.mapping_applied
        ? "package mapping applied"
        : planned.mapping_errors?.length
          ? `mapping: ${planned.mapping_errors[0]}`
          : "assign roles in Mapping";
      setStatus(
        `Package staged · ${cards.length} CSV(s) · ${mapNote}${sid ? ` · session ${sid}` : ""}`,
      );
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  const openSession = useCallback(async (id: string) => {
    if (!hasToken()) {
      setError("Sign in to load sessions.");
      return;
    }
    setBusy("load");
    setError("");
    try {
      const data = await fetchAgentSessionFusionPreview(id);
      if (!data.ok) throw new Error(data.error ?? "load failed");
      setSessionId(id);
      setStatus(
        `Session ${id} — ${data.row_count?.toLocaleString() ?? "?"} rows ready for plan/execute via agent or UT3 panel.`,
      );
      void datasetFromFusionPreview(data, id);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, []);

  async function saveToArrow() {
    if (!sessionId) {
      setError("Upload or open a session first.");
      return;
    }
    setBusy("arrow");
    try {
      const out = await saveAgentSessionToArrow(sessionId);
      if (!out.ok) throw new Error(out.error ?? "save failed");
      setStatus(
        `Saved to Arrow (${out.dataset?.id ?? sessionId}). Next: Analytics & rules → run batch, or Charts for trends.`,
      );
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  const equipKeys = zipManifest?.equipment ? Object.keys(zipManifest.equipment) : [];

  return (
    <div className="page page-wide csv-workbench-page">
      <PageHeader
        title="CSV import"
        subtitle="Drop building CSVs or an openfdd_package_v1 ZIP for safe inspect, mapping, and historian import."
      />

      <div className="toolbar toolbar-spaced csv-workbench-steps">
        <span className="muted">Steps: Upload → Mapping → Arrow / Plots</span>
        <button
          type="button"
          className={showMapping ? "primary-btn" : "secondary-btn"}
          onClick={() => setShowMapping((v) => !v)}
        >
          {showMapping ? "Hide mapping" : "Open mapping"}
        </button>
      </div>

      {error ? <p className="error">{error}</p> : null}
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
          if (busy) return;
          void ingestFiles(e.dataTransfer.files);
        }}
      >
        <p className="csv-drop-title">Drop CSV or ZIP package here</p>
        <p className="muted">
          Multiple CSVs append to one session · ZIP is inspected safely (no traversal / bomb extracts)
        </p>
        <label className="primary-btn csv-drop-btn">
          {busy === "upload" || busy === "zip" ? (
            <>
              <Spinner inline /> Uploading…
            </>
          ) : (
            "Choose files"
          )}
          <input
            type="file"
            accept=".csv,.zip,text/csv,application/zip"
            multiple
            hidden
            disabled={!!busy}
            onChange={(e) => {
              if (e.target.files?.length) void ingestFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {zipManifest ? (
        <section className="panel csv-zip-manifest">
          <h3 className="panel-title">Package manifest</h3>
          <p className="muted">
            {zipManifest.package_id ? (
              <>
                Package <code>{zipManifest.package_id}</code>
                {zipManifest.filename ? ` · ${zipManifest.filename}` : ""}
                {typeof zipManifest.zip_bytes === "number"
                  ? ` · ${(zipManifest.zip_bytes / 1024).toFixed(1)} KB`
                  : ""}
              </>
            ) : (
              "Inspected package"
            )}
          </p>
          <ul className="csv-zip-manifest-list">
            <li>
              <strong>{zipManifest.csv_files?.length ?? 0}</strong> CSV file(s)
              {zipManifest.weather_csvs?.length
                ? ` · ${zipManifest.weather_csvs.length} weather`
                : ""}
            </li>
            <li>
              <strong>{equipKeys.length}</strong> equipment folder(s)
              {equipKeys.length ? `: ${equipKeys.slice(0, 8).join(", ")}${equipKeys.length > 8 ? "…" : ""}` : ""}
            </li>
            <li>
              Mapping:{" "}
              {zipManifest.mapping_status?.valid
                ? "valid Phase-1 column_map.json"
                : zipManifest.mapping_status?.present
                  ? (zipManifest.mapping_status.errors?.[0] ?? "present — needs review")
                  : "missing — assign roles after staging"}
            </li>
          </ul>
          {zipManifest.csv_files && zipManifest.csv_files.length > 0 ? (
            <details className="csv-zip-file-details">
              <summary>CSV paths ({zipManifest.csv_files.length})</summary>
              <ul className="csv-upload-results">
                {zipManifest.csv_files.map((p) => (
                  <li key={p} className="csv-upload-ok">
                    <code>{p}</code>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <div className="toolbar toolbar-spaced" style={{ marginTop: "0.75rem" }}>
            <button
              type="button"
              className="primary-btn"
              disabled={!!busy || !zipManifest.package_id}
              onClick={() => void proceedZipToMapping()}
            >
              {busy === "plan" ? "Staging…" : "Proceed to mapping"}
            </button>
          </div>
        </section>
      ) : null}

      {uploadCards.length > 0 ? (
        <section className="panel">
          <h3 className="panel-title">Parse results</h3>
          <ul className="csv-upload-results">
            {uploadCards.map((card, i) => (
              <li key={`${card.filename}-${i}`} className={card.error ? "csv-upload-reject" : "csv-upload-ok"}>
                <strong>
                  {card.error ? "✗" : "✓"} {card.filename}
                </strong>
                {card.error ? (
                  <span className="muted"> — {card.error}</span>
                ) : (
                  <span className="muted">
                    {" "}
                    — {card.profile?.row_count?.toLocaleString() ?? "?"} rows
                    {card.profile?.headers?.includes("ts") ||
                    card.profile?.headers?.includes("timestamp")
                      ? " · timestamp detected"
                      : " · no timestamp column"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {showMapping ? (
        <CsvMappingPanel defaultDatasetId={sessionId} availableColumns={availableColumns} />
      ) : null}

      <section className="panel">
        <div className="toolbar toolbar-spaced">
          {sessionId ? (
            <>
              <span className="muted">
                Active session: <code>{sessionId}</code>
              </span>
              <button
                type="button"
                className="secondary-btn"
                disabled={!!busy}
                onClick={() => void saveToArrow()}
              >
                {busy === "arrow" ? "Saving…" : "Save session to Arrow"}
              </button>
            </>
          ) : (
            <span className="muted">Sessions appear below after upload.</span>
          )}
          <Link className="secondary-btn" to="/sql-fdd">
            Run analytics
          </Link>
          <Link className="secondary-btn" to="/plot">
            Open Charts
          </Link>
        </div>
        <CsvSessionSidecart activeSessionId={sessionId} onOpenSession={(id) => void openSession(id)} />
      </section>
    </div>
  );
}
