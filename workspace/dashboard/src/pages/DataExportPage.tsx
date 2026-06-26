import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch, apiDownloadBlob } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type ExportMeta = {
  ok?: boolean;
  exports?: {
    id: string;
    label: string;
    format: string;
    path: string;
    row_count?: number;
    available?: boolean;
    data_source_label?: string;
  }[];
};

export default function DataExportPage() {
  const [meta, setMeta] = useState<ExportMeta | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [hours, setHours] = useState(24);

  useEffect(() => {
    apiFetch<ExportMeta>("/api/export/meta")
      .then(setMeta)
      .catch((e) => setError(formatApiError(e)));
  }, []);

  async function download(path: string, label: string) {
    setStatus("");
    setError("");
    try {
      const qs = path.includes("?") ? "&" : "?";
      const url = `${path}${qs}hours=${hours}`;
      const { blob, filename } = await apiDownloadBlob(url);
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename.endsWith(".csv") ? filename : `${label.replace(/\s+/g, "_").toLowerCase()}.csv`;
      a.click();
      URL.revokeObjectURL(blobUrl);
      setStatus(`Downloaded ${label}`);
    } catch (e) {
      setError(formatApiError(e));
    }
  }

  const exports = meta?.exports ?? [];

  return (
    <div className="page page-wide">
      <PageHeader
        title="Data export"
        subtitle="Download CSV extracts for historian, faults, model points, rules, and validation runs."
      />

      {error ? <div className="error-banner">{error}</div> : null}
      {status ? <div className="status-banner">{status}</div> : null}

      <section className="panel">
        <div className="toolbar">
          <label>
            Default range (hours)
            <input type="number" min={1} max={720} value={hours} onChange={(e) => setHours(Number(e.target.value))} />
          </label>
        </div>

        <div className="table-like export-list">
          {exports.length === 0 ? (
            <p className="muted-copy">No export endpoints reported — check bridge export sidecar configuration.</p>
          ) : (
            exports.map((item) => (
              <div key={item.id} className="table-row export-row">
                <div>
                  <strong>{item.label}</strong>
                  <p className="muted-copy">
                    {item.format.toUpperCase()} · {item.row_count ?? 0} rows
                    {item.data_source_label ? ` · ${item.data_source_label}` : ""}
                    {!item.available ? " · empty until historian has data" : ""}
                  </p>
                </div>
                <button type="button" className="primary-btn" onClick={() => void download(item.path, item.label)}>
                  Download
                </button>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
