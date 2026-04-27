import { useState } from "react";
import { desktopFetch } from "../lib/api";

type IngestResponse = {
  rows: number;
  metrics: string[];
  dropped_rows?: number;
};

export function CsvImportPage() {
  const [siteId, setSiteId] = useState("");
  const [source, setSource] = useState("csv");
  const [csvPath, setCsvPath] = useState("");
  const [output, setOutput] = useState("Drop or select a CSV path and run import.");

  async function runImport(path: string) {
    try {
      const out = await desktopFetch<IngestResponse>("/ingest/csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: siteId, source, csv_path: path }),
      });
      setOutput(`Rows: ${out.rows}\nDropped: ${out.dropped_rows ?? 0}\nMetrics: ${out.metrics.join(", ")}`);
    } catch (e) {
      setOutput(e instanceof Error ? e.message : String(e));
    }
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0] as File & { path?: string };
    if (!file) return;
    setCsvPath(file.path || file.name);
    void runImport(file.path || file.name);
  }

  return (
    <div className="card">
      <h2 className="title">CSV Import</h2>
      <div className="grid-two">
        <div>
          <label>Site ID</label>
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site id" />
        </div>
        <div>
          <label>Source</label>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="csv" />
        </div>
      </div>
      <div className="drop-zone" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
        Drag and drop CSV file here
      </div>
      <div className="grid-two">
        <input value={csvPath} onChange={(e) => setCsvPath(e.target.value)} placeholder="Path to CSV file" />
        <button onClick={() => void runImport(csvPath)}>Import CSV</button>
      </div>
      <p style={{ color: "var(--muted)", marginTop: 8, marginBottom: 0 }}>
        Use full file path for reliability (example: <code>C:/Users/ben/Documents/AHU7.csv</code>).
      </p>
      <textarea readOnly value={output} style={{ marginTop: 12, minHeight: 120 }} />
    </div>
  );
}
