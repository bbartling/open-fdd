import { useCallback, useState } from "react";
import PageHeader from "../components/PageHeader";
import CsvSessionSidecart from "../components/CsvSessionSidecart";
import PackageImportPanel from "../components/PackageImportPanel";
import Spinner from "../components/Spinner";
import { hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  uploadFilesForPreview,
  type CsvPreviewFileProfile,
} from "../lib/csvImportUpload";
import {
  uploadPackageZip,
  type PackageImportResponse,
} from "../lib/csvPackageImport";
import {
  datasetFromFusionPreview,
  fetchAgentSessionFusionPreview,
  saveAgentSessionToArrow,
} from "../lib/csvAgentSession";

type UploadCard = CsvPreviewFileProfile & { sessionId?: string };

export default function CsvWorkbenchPage() {
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [uploadCards, setUploadCards] = useState<UploadCard[]>([]);
  const [packageResult, setPackageResult] = useState<PackageImportResponse | null>(null);

  const ingestPackage = useCallback(async (zips: File[]) => {
    setError("");
    setBusy("package");
    try {
      let last: PackageImportResponse | null = null;
      for (const zip of zips) {
        const res = await uploadPackageZip(zip);
        if (!res.ok) {
          const missing = res.missing_maps?.length
            ? ` — missing maps: ${res.missing_maps.join(", ")}`
            : "";
          throw new Error(`${res.error ?? "package load failed"}${missing}`);
        }
        last = res;
      }
      if (last) {
        setPackageResult(last);
        setStatus(
          `Package ${last.building_id} ingested — ${last.equipment_written ?? 0} equipment, ${last.total_rows?.toLocaleString() ?? "?"} rows. FDD rules can run now.`,
        );
      }
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, []);

  const ingestFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!hasToken()) {
        setError("Sign in to upload CSV files.");
        return;
      }
      const all = Array.from(files);
      const zips = all.filter((f) => f.name.toLowerCase().endsWith(".zip"));
      if (zips.length) {
        await ingestPackage(zips);
      }
      const list = all.filter((f) => f.name.toLowerCase().endsWith(".csv"));
      if (!list.length) {
        if (!zips.length) setError("Choose one or more .csv files or an openfdd_package_v1 .zip.");
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
    [sessionId, ingestPackage],
  );

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
      setStatus(`Saved to Arrow (${out.dataset_id ?? sessionId}). Open Plots to chart.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="page page-wide csv-workbench-page">
      <PageHeader
        title="CSV import"
        subtitle="Drop building CSVs for server-side preview, preflight, and historian import — same pipeline as MCP agents."
      />

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
          void ingestFiles(e.dataTransfer.files);
        }}
      >
        <p className="csv-drop-title">Drop CSV files or an openfdd_package_v1 .zip here</p>
        <p className="muted">
          Multiple CSVs append to one import session · zip packages (manifest.json + per-equipment
          history_wide.csv + Haystack column maps) ingest straight to the FDD store
        </p>
        <label className="primary-btn csv-drop-btn">
          {busy === "upload" || busy === "package" ? (
            <>
              <Spinner inline /> Uploading…
            </>
          ) : (
            "Choose files"
          )}
          <input
            type="file"
            accept=".csv,text/csv,.zip,application/zip"
            multiple
            hidden
            disabled={busy === "upload" || busy === "package"}
            onChange={(e) => {
              if (e.target.files?.length) void ingestFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {packageResult ? <PackageImportPanel result={packageResult} /> : null}

      {uploadCards.length > 0 ? (
        <section className="panel">
          <h3 className="panel-title">Parse results</h3>
          <ul className="csv-upload-results">
            {uploadCards.map((card, i) => (
              <li key={`${card.filename}-${i}`} className={card.error ? "csv-upload-reject" : "csv-upload-ok"}>
                <strong>{card.error ? "✗" : "✓"} {card.filename}</strong>
                {card.error ? (
                  <span className="muted"> — {card.error}</span>
                ) : (
                  <span className="muted">
                    {" "}
                    — {card.profile?.row_count?.toLocaleString() ?? "?"} rows
                    {card.profile?.headers?.includes("ts") || card.profile?.headers?.includes("timestamp")
                      ? " · timestamp detected"
                      : " · no timestamp column"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="panel">
        <div className="toolbar toolbar-spaced">
          {sessionId ? (
            <>
              <span className="muted">Active session: <code>{sessionId}</code></span>
              <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void saveToArrow()}>
                {busy === "arrow" ? "Saving…" : "Save session to Arrow"}
              </button>
            </>
          ) : (
            <span className="muted">Sessions appear below after upload.</span>
          )}
          <a className="secondary-btn" href="/plot">
            Open Plots
          </a>
        </div>
        <CsvSessionSidecart activeSessionId={sessionId} onOpenSession={(id) => void openSession(id)} />
      </section>
    </div>
  );
}
