import { useState } from "react";
import { bridgeBase, desktopFetch } from "../lib/api";
import { useOptionalSite } from "../contexts/site-context";

type IngestResponse = {
  rows: number;
  metrics: string[];
  dropped_rows?: number;
};

type ImportLog = {
  name: string;
  ok: boolean;
  message: string;
};

export function CsvImportPage() {
  const siteContext = useOptionalSite();
  const [siteId, setSiteId] = useState(() => siteContext?.selectedSiteId ?? "");
  const [source, setSource] = useState("csv");
  const [pickedFiles, setPickedFiles] = useState<File[]>([]);
  const [importLogs, setImportLogs] = useState<ImportLog[]>([]);
  const [output, setOutput] = useState("Choose one or more CSV files and import.");

  async function runUpload(file: File): Promise<ImportLog> {
    try {
      const effectiveSiteId = siteId || siteContext?.selectedSiteId || "";
      if (!effectiveSiteId) {
        return { name: file.name, ok: false, message: "Set or select a site first." };
      }
      const formData = new FormData();
      formData.append("site_id", effectiveSiteId);
      formData.append("source", source);
      formData.append("file", file, file.name);
      const res = await fetch(`${bridgeBase}/ingest/csv/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        return { name: file.name, ok: false, message: `Bridge error ${res.status}: ${await res.text()}` };
      }
      const out = (await res.json()) as IngestResponse;
      return {
        name: file.name,
        ok: true,
        message: `Rows: ${out.rows}; Dropped: ${out.dropped_rows ?? 0}; Metrics: ${out.metrics.join(", ")}`,
      };
    } catch (e) {
      return { name: file.name, ok: false, message: e instanceof Error ? e.message : String(e) };
    }
  }

  async function processFiles(files: File[]) {
    if (files.length === 0) return;
    const logs: ImportLog[] = [];
    for (const file of files) {
      logs.push(await runUpload(file));
    }
    setImportLogs(logs);
    setOutput(logs.map((entry) => `${entry.ok ? "OK" : "ERROR"} ${entry.name}: ${entry.message}`).join("\n"));
  }

  return (
    <div className="card">
      <h2 className="title">CSV Import</h2>
      <div className="grid-two">
        <div>
          <label>Site ID</label>
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site id" />
          {!siteId && siteContext?.selectedSiteId && (
            <small className="muted">Using selected site from top bar.</small>
          )}
        </div>
        <div>
          <label>Source</label>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="csv" />
        </div>
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "inline-block", cursor: "pointer" }}>
          <span style={{ display: "inline-block", padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 9 }}>
            Choose CSV file
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length === 0) return;
              setPickedFiles(files);
              void processFiles(files);
              e.target.value = "";
            }}
          />
        </label>
        {pickedFiles.length > 0 && (
          <span style={{ marginLeft: 10, color: "var(--muted)", fontSize: 13 }}>
            Selected: {pickedFiles.length} file(s)
          </span>
        )}
      </div>
      <p style={{ color: "var(--muted)", marginTop: 8, marginBottom: 0 }}>
        Picker-only mode for reliable cross-platform behavior (Windows/macOS/Linux).
      </p>
      {importLogs.length > 0 && (
        <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}>
          <strong>Processed files</strong>
          <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
            {importLogs.map((entry) => (
              <li key={`${entry.name}-${entry.message}`} style={{ color: entry.ok ? "var(--text)" : "var(--danger)" }}>
                {entry.name}: {entry.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea readOnly value={output} style={{ marginTop: 12, minHeight: 120 }} />
    </div>
  );
}
