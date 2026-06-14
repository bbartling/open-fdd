import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { ModelPayload, parseImportPayload } from "../lib/modelImport";

type Props = {
  onStatus: (msg: string) => void;
  onImported?: () => void;
};

export default function ModelImportExportPanel({ onStatus, onImported }: Props) {
  const [exportText, setExportText] = useState("");
  const [importText, setImportText] = useState("");
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const loadExport = useCallback(async () => {
    setExportLoading(true);
    try {
      const model = await apiFetch<ModelPayload>("/api/model/export");
      setExportText(JSON.stringify(model, null, 2));
    } catch (error) {
      onStatus(`Export failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setExportLoading(false);
    }
  }, [onStatus]);

  useEffect(() => {
    void loadExport();
  }, [loadExport]);

  async function doImport() {
    if (!importText.trim()) {
      onStatus("Paste JSON in the import box first (or upload a file).");
      return;
    }
    try {
      const payload = parseImportPayload(importText);
      const confirmed = window.confirm(
        "Import with replace=true will overwrite sites, equipment, and points. Continue?",
      );
      if (!confirmed) {
        onStatus("Import canceled.");
        return;
      }
      setImportLoading(true);
      const resp = await apiFetch<{ sites: number; equipment: number; points: number }>("/api/model/import", {
        method: "POST",
        body: JSON.stringify({ payload, replace: true }),
      });
      onStatus(`Imported sites=${resp.sites}, equipment=${resp.equipment}, points=${resp.points}. TTL synced.`);
      setImportText("");
      await loadExport();
      onImported?.();
    } catch (error) {
      onStatus(`Import failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setImportLoading(false);
    }
  }

  function downloadExport() {
    if (!exportText.trim()) return;
    const blob = new Blob([exportText], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "openfdd-data-model.json";
    a.click();
    URL.revokeObjectURL(url);
    onStatus("Downloaded openfdd-data-model.json");
  }

  async function onImportFile(file: File | null) {
    if (!file) return;
    try {
      setImportText(await file.text());
      onStatus(`Loaded ${file.name} — review below, then click Import.`);
    } catch (error) {
      onStatus(`File load failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  return (
    <div className="dm-io-grid">
      <section className="dm-io-panel panel">
        <header className="dm-io-head">
          <h3 className="panel-title">Export JSON</h3>
          <div className="row">
            <button type="button" className="secondary-btn" disabled={exportLoading} onClick={() => void loadExport()}>
              {exportLoading ? "Loading…" : "Refresh"}
            </button>
            <button type="button" disabled={!exportText.trim()} onClick={downloadExport}>
              Download
            </button>
          </div>
        </header>
        <p className="muted">
          Full <code>model.json</code> for LLM tagging or backup. After BACnet discovery, run{" "}
          <strong>Sync poll → model</strong> below keeps export aligned with live polling.
        </p>
        <textarea
          readOnly
          className="dm-json-editor"
          value={exportText}
          placeholder="Click Refresh to load the current model…"
        />
      </section>

      <section className="dm-io-panel panel">
        <header className="dm-io-head">
          <h3 className="panel-title">Import JSON</h3>
          <label className="secondary-btn file-upload-btn">
            Upload file
            <input
              type="file"
              accept=".json,application/json,text/plain"
              hidden
              onChange={(e) => {
                void onImportFile(e.target.files?.[0] ?? null);
                e.target.value = "";
              }}
            />
          </label>
        </header>
        <p className="muted">
          Paste tagged JSON with <code>sites</code>, <code>equipment</code>, and <code>points</code> arrays. Supports{" "}
          <code>```json</code> fences and <code>import_ready_json</code> wrappers.
        </p>
        <textarea
          className="dm-json-editor"
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder='{"sites":[…],"equipment":[…],"points":[…]}'
          spellCheck={false}
        />
        <div className="row">
          <button type="button" disabled={importLoading || !importText.trim()} onClick={() => void doImport()}>
            {importLoading ? "Importing…" : "Import (replace model)"}
          </button>
          <button type="button" className="secondary-btn" disabled={!importText} onClick={() => setImportText("")}>
            Clear import box
          </button>
        </div>
      </section>
    </div>
  );
}
