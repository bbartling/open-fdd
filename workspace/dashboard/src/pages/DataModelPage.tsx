import { useState } from "react";
import { apiFetch } from "../lib/api";
import { DATA_MODEL_REDESIGN_PROMPT } from "../lib/llm-prompts";
import { ModelPayload, parseImportPayload } from "../lib/modelImport";

export default function DataModelPage() {
  const [activeTab, setActiveTab] = useState<"export" | "import">("export");
  const [exportJsonText, setExportJsonText] = useState("");
  const [importJsonText, setImportJsonText] = useState("");
  const [out, setOut] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [ttlText, setTtlText] = useState("");
  const [copiedKey, setCopiedKey] = useState("");

  async function copyText(key: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(""), 1200);
    } catch (error) {
      setOut(`Copy failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function doExport() {
    try {
      const model = await apiFetch<ModelPayload>("/api/model/export");
      setExportJsonText(JSON.stringify(model, null, 2));
      setOut("Exported model JSON.");
    } catch (error) {
      setOut(`Export failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function ensureExportJsonInEditor(): Promise<string> {
    const trimmed = String(exportJsonText || "").trim();
    if (trimmed) {
      return exportJsonText;
    }
    const model = await apiFetch<ModelPayload>("/api/model/export");
    const text = JSON.stringify(model, null, 2);
    setExportJsonText(text);
    return text;
  }

  async function downloadJsonFile() {
    try {
      const source = await ensureExportJsonInEditor();
      const payload = parseImportPayload(source);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "open-fdd-data-model.json";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setOut("Downloaded open-fdd-data-model.json");
    } catch (error) {
      setOut(`Download failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function copyImportReadyJson() {
    try {
      const source = await ensureExportJsonInEditor();
      const payload = parseImportPayload(source);
      await copyText("import-ready", JSON.stringify(payload, null, 2));
      setOut("Copied import-ready JSON (sites/equipment/points only).");
    } catch (error) {
      setOut(`Copy failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function doImport() {
    try {
      const payload = parseImportPayload(importJsonText);
      const confirmed = window.confirm(
        "Import with replace=true will overwrite the existing model. Continue?",
      );
      if (!confirmed) {
        setOut("Import canceled.");
        return;
      }
      const resp = await apiFetch<{ sites: number; equipment: number; points: number }>(
        "/api/model/import",
        {
          method: "POST",
          body: JSON.stringify({ payload, replace: true }),
        },
      );
      setOut(`Imported sites=${resp.sites}, equipment=${resp.equipment}, points=${resp.points}. TTL synced.`);
      setImportJsonText("");
    } catch (error) {
      setOut(`Import failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function onImportJsonFile(file: File | null) {
    if (!file) return;
    try {
      setImportJsonText(await file.text());
      setOut(`Loaded JSON file: ${file.name}`);
    } catch (error) {
      setOut(`File load failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function doViewTtl() {
    setTtlLoading(true);
    setTtlText("");
    try {
      const token = sessionStorage.getItem("ofdd_token");
      const resp = await fetch("/api/model/ttl?save=false", {
        headers: {
          Accept: "text/turtle",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setTtlText(await resp.text());
      setOut("Loaded TTL graph below.");
    } catch (error) {
      setTtlText("");
      setOut(`TTL view failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTtlLoading(false);
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data Model BRICK</h2>
      <p className="muted">
        Export/import sites, equipment, and points. Python Rule Lab rules bind to fdd_input and brick_type
        from this model — no YAML rule files.
      </p>
      <div className="tab-row">
        <button
          type="button"
          className={activeTab === "export" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("export")}
        >
          Export
        </button>
        <button
          type="button"
          className={activeTab === "import" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("import")}
        >
          Import
        </button>
      </div>

      {activeTab === "export" ? (
        <div className="row">
          <button type="button" onClick={() => void doExport()}>
            Export JSON
          </button>
          <button type="button" className="secondary-btn" onClick={() => void downloadJsonFile()}>
            Download file
          </button>
          <button type="button" className="secondary-btn" onClick={() => void copyImportReadyJson()}>
            {copiedKey === "import-ready" ? "Copied JSON" : "Copy JSON"}
          </button>
        </div>
      ) : (
        <div className="stack-page">
          <div className="row">
            <button type="button" onClick={() => void doImport()}>
              Import JSON
            </button>
            <label className="secondary-btn file-upload-btn">
              Upload JSON file
              <input
                type="file"
                accept=".json,application/json,text/plain"
                hidden
                onChange={(e) => {
                  void onImportJsonFile(e.target.files?.[0] ?? null);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
          <p className="muted">Paste JSON or upload an LLM-generated import_ready payload.</p>
        </div>
      )}

      <textarea
        className="model-editor"
        value={activeTab === "import" ? importJsonText : exportJsonText}
        onChange={(e) => {
          if (activeTab === "import") setImportJsonText(e.target.value);
          else setExportJsonText(e.target.value);
        }}
        placeholder={
          activeTab === "import"
            ? "Paste import JSON here (sites / equipment / points)."
            : "Click Export JSON to load the current model."
        }
      />
      <textarea readOnly className="status-line" value={out} />
      <div className="row">
        <button type="button" className="secondary-btn" onClick={() => void copyText("prompt", DATA_MODEL_REDESIGN_PROMPT)}>
          {copiedKey === "prompt" ? "Copied Prompt" : "Copy LLM Prompt"}
        </button>
        <button type="button" onClick={() => void doViewTtl()}>
          {ttlLoading ? "Loading TTL…" : "View BRICK TTL"}
        </button>
      </div>
      <textarea readOnly className="ttl-editor prompt-preview" value={DATA_MODEL_REDESIGN_PROMPT} />
      <textarea
        readOnly
        className="ttl-editor"
        value={ttlText}
        placeholder="TTL content appears here after View BRICK TTL."
      />
    </div>
  );
}
