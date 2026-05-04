import { useState } from "react";
import { bridgeBase } from "../lib/api";
import { useOptionalSite } from "../contexts/site-context";

type IngestResponse = {
  rows: number;
  metrics: string[];
  dropped_rows?: number;
  preview_rows?: Array<Record<string, unknown>>;
  parse_error?: string;
};

type ImportLog = {
  name: string;
  ok: boolean;
  message: string;
  preview?: Array<Record<string, unknown>>;
  parseError?: string;
};

export function CsvImportPage() {
  const siteContext = useOptionalSite();
  const [siteId, setSiteId] = useState(() => siteContext?.selectedSiteId ?? "");
  const [source, setSource] = useState("csv");
  const [equipmentId, setEquipmentId] = useState("");
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
      if (equipmentId.trim()) {
        formData.append("equipment_id", equipmentId.trim());
      }
      formData.append("file", file, file.name);
      const res = await fetch(`${bridgeBase}/ingest/csv/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        return { name: file.name, ok: false, message: `Bridge error ${res.status}: ${await res.text()}` };
      }
      const out = (await res.json()) as IngestResponse;
      if (out.parse_error) {
        return {
          name: file.name,
          ok: false,
          message: `Rows: ${out.rows}; Dropped: ${out.dropped_rows ?? 0}. ${out.parse_error}`,
          parseError: out.parse_error,
          preview: Array.isArray(out.preview_rows) ? out.preview_rows : [],
        };
      }
      const metricsLine =
        out.metrics && out.metrics.length > 0 ? out.metrics.join(", ") : "(none — check encoding/delimiter or time column)";
      return {
        name: file.name,
        ok: true,
        message: `Rows: ${out.rows}; Dropped: ${out.dropped_rows ?? 0}; Metrics: ${metricsLine}`,
        preview: Array.isArray(out.preview_rows) && out.preview_rows.length > 0 ? out.preview_rows : undefined,
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
          <label>Site</label>
          <select value={siteId || siteContext?.selectedSiteId || ""} onChange={(e) => setSiteId(e.target.value)}>
            {(siteContext?.sites ?? []).length === 0 && <option value="">No sites</option>}
            {(siteContext?.sites ?? []).map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
          {!siteId && siteContext?.selectedSiteId && (
            <small className="muted">Using selected site from top bar.</small>
          )}
        </div>
        <div>
          <label>Source</label>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="csv" />
        </div>
        <div>
          <label>Equipment ID (optional)</label>
          <input
            value={equipmentId}
            onChange={(e) => setEquipmentId(e.target.value)}
            placeholder="attach to an existing AHU"
          />
        </div>
      </div>
      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "inline-block", cursor: "pointer" }}>
          <span className="file-picker-btn">
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
        Picker-only mode for reliable cross-platform behavior (Windows/macOS/Linux). If the site already has one
        equipment record, uploads will attach there automatically; otherwise, paste an equipment ID to keep
        repeated CSV batches on the same AHU.
      </p>
      {importLogs.length > 0 && (
        <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}>
          <strong>Processed files</strong>
          <ul style={{ margin: "8px 0 0", paddingLeft: 18, listStyle: "none" }}>
            {importLogs.map((entry) => (
              <li
                key={`${entry.name}-${entry.message}`}
                style={{
                  marginBottom: 12,
                  color: entry.ok ? "var(--text)" : "var(--danger)",
                  borderBottom: "1px solid var(--border)",
                  paddingBottom: 10,
                }}
              >
                <div>
                  <strong>{entry.name}</strong>: {entry.message}
                </div>
                {entry.preview && entry.preview.length > 0 ? (
                  <div style={{ marginTop: 8 }}>
                    <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                      First rows stored in Feather (timestamp + metrics), same as a pandas <code>head()</code>:
                    </div>
                    <pre
                      style={{
                        margin: 0,
                        maxHeight: 220,
                        overflow: "auto",
                        padding: 8,
                        fontSize: 12,
                        borderRadius: 8,
                        border: "1px solid var(--border)",
                        background: "var(--input-bg)",
                      }}
                    >
                      {JSON.stringify(entry.preview, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea readOnly value={output} style={{ marginTop: 12, minHeight: 120 }} />
    </div>
  );
}
