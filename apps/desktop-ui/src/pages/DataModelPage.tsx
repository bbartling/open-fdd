import { useState } from "react";
import { desktopFetch, desktopFetchText } from "../lib/api";
import { DATA_MODEL_REDESIGN_PROMPT } from "../lib/llm-prompts";

type ModelPayload = {
  sites: Array<Record<string, unknown>>;
  equipment: Array<Record<string, unknown>>;
  points: Array<Record<string, unknown>>;
};

export function DataModelPage() {
  const [activeTab, setActiveTab] = useState<"export" | "import">("export");
  /** Last export / model snapshot (Export tab only). */
  const [exportJsonText, setExportJsonText] = useState("");
  /** Draft for POST /model/import (Import tab only). */
  const [importJsonText, setImportJsonText] = useState("");
  const [out, setOut] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [ttlText, setTtlText] = useState("");
  const [copiedKey, setCopiedKey] = useState("");

  async function copyText(key: string, value: string) {
    try {
      let copied = false;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      } else {
        const el = document.createElement("textarea");
        el.value = value;
        try {
          document.body.appendChild(el);
          el.select();
          copied = document.execCommand("copy");
        } finally {
          document.body.removeChild(el);
        }
      }
      if (!copied) {
        throw new Error("Clipboard copy was blocked.");
      }
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(""), 1200);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Copy failed: ${message}`);
    }
  }

  async function doExport() {
    try {
      const model = await desktopFetch<ModelPayload>("/model/export");
      setExportJsonText(JSON.stringify(model, null, 2));
      setOut("Exported model JSON.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Export failed: ${message}`);
    }
  }

  async function ensureExportJsonInEditor(): Promise<string> {
    const trimmed = String(exportJsonText || "").trim();
    if (trimmed) {
      return exportJsonText;
    }
    const model = await desktopFetch<ModelPayload>("/model/export");
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
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Download failed: ${message}`);
    }
  }

  async function copyImportReadyJson() {
    try {
      const source = await ensureExportJsonInEditor();
      const payload = parseImportPayload(source);
      const text = JSON.stringify(payload, null, 2);
      await copyText("import-ready", text);
      setOut("Copied import-ready JSON (sites/equipment/points only).");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Copy import-ready JSON failed: ${message}`);
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
      const resp = await desktopFetch<{ sites: number; equipment: number; points: number }>("/model/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload, replace: true }),
      });
      setOut(`Imported sites=${resp.sites}, equipment=${resp.equipment}, points=${resp.points}.`);
      setImportJsonText("");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Import failed: ${message}`);
    }
  }

  async function onImportJsonFile(file: File | null) {
    if (!file) {
      return;
    }
    try {
      const text = await file.text();
      setImportJsonText(text);
      setOut(`Loaded JSON file: ${file.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`File load failed: ${message}`);
    }
  }

  async function doViewTtl() {
    setTtlLoading(true);
    setTtlText("");
    try {
      const ttl = await desktopFetchText("/data-model/ttl?save=false", { headers: { Accept: "text/plain" } });
      setTtlText(ttl);
      setOut("Loaded full TTL graph below.");
    } catch (error) {
      setTtlText("");
      const message = error instanceof Error ? error.message : String(error);
      setOut(`TTL view failed: ${message}`);
    } finally {
      setTtlLoading(false);
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data Model BRICK</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button
          className={activeTab === "export" ? "" : "secondary-btn"}
          type="button"
          onClick={() => setActiveTab("export")}
        >
          Export
        </button>
        <button
          className={activeTab === "import" ? "" : "secondary-btn"}
          type="button"
          onClick={() => setActiveTab("import")}
        >
          Import
        </button>
      </div>

      {activeTab === "export" ? (
        <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
          <button onClick={() => void doExport()}>Export JSON</button>
          <button className="secondary-btn" onClick={() => void downloadJsonFile()}>
            Export file
          </button>
          <button className="secondary-btn" onClick={() => void copyImportReadyJson()}>
            {copiedKey === "import-ready" ? "Copied JSON" : "Copy JSON"}
          </button>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button onClick={() => void doImport()}>Import JSON</button>
            <label className="secondary-btn" style={{ display: "inline-flex", alignItems: "center", cursor: "pointer" }}>
              Upload JSON file
              <input
                type="file"
                accept=".json,application/json,text/plain"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null;
                  void onImportJsonFile(file);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
          <div className="muted">
            Paste JSON directly or upload an LLM-generated JSON file, then click Import JSON.
          </div>
        </div>
      )}

      <textarea
        value={activeTab === "import" ? importJsonText : exportJsonText}
        onChange={(e) => {
          if (activeTab === "import") {
            setImportJsonText(e.target.value);
          } else {
            setExportJsonText(e.target.value);
          }
        }}
        placeholder={
          activeTab === "import"
            ? "Paste import JSON here (sites / equipment / points). Switch to Export for the live model snapshot."
            : "Click Export JSON to load the current model. Import uses a separate box on the Import tab."
        }
        style={{ minHeight: 260 }}
      />
      <textarea readOnly value={out} style={{ marginTop: 10, minHeight: 64 }} />
      <div style={{ marginTop: 10, marginBottom: 6 }}>
        <button className="secondary-btn" onClick={() => void copyText("prompt", DATA_MODEL_REDESIGN_PROMPT)}>
          {copiedKey === "prompt" ? "Copied Prompt" : "Copy LLM Prompt"}
        </button>
      </div>
      <textarea
        readOnly
        value={DATA_MODEL_REDESIGN_PROMPT}
        style={{ marginTop: 10, minHeight: 220, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}
      />
      <div style={{ marginTop: 10, marginBottom: 6 }}>
        <button onClick={() => void doViewTtl()}>{ttlLoading ? "Loading TTL..." : "View full data model (TTL)"}</button>
      </div>
      <textarea
        readOnly
        value={ttlText}
        placeholder="TTL content will appear here after clicking 'View full data model (TTL)'."
        style={{ marginTop: 10, minHeight: 420, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}
      />
    </div>
  );
}

function parseImportPayload(input: string): ModelPayload {
  const raw = String(input || "").trim();
  if (!raw) {
    throw new Error("JSON input is empty.");
  }
  let parsed: unknown;
  try {
    parsed = parseJsonLenient(raw);
  } catch {
    const fromSections = extractImportJsonFromFileSections(raw);
    if (!fromSections) {
      throw new Error(
        "Could not parse JSON. Paste either plain import JSON, a fenced ```json block, or ChatGPT === FILE: open_fdd_data_model_import_ready.json === sections.",
      );
    }
    parsed = fromSections;
  }
  const extracted = extractImportShape(parsed);
  return validateImportShape(extracted);
}

function parseJsonLenient(raw: string): unknown {
  const attempts: string[] = [raw];
  const fenced = extractJsonFence(raw);
  if (fenced) {
    attempts.push(fenced);
    const escapedFenced = escapeBackslashesInLikelyPathFields(fenced);
    if (escapedFenced !== fenced) attempts.push(escapedFenced);
  }
  const withEscapedRefs = escapeBackslashesInLikelyPathFields(raw);
  if (withEscapedRefs !== raw) attempts.push(withEscapedRefs);
  for (const candidate of attempts) {
    try {
      return JSON.parse(candidate);
    } catch {
      // continue attempts
    }
  }
  throw new Error(
    "Invalid JSON. If this came from an LLM, ensure import_ready_json is plain JSON with escaped Windows paths.",
  );
}

function extractJsonFence(text: string): string | null {
  const m = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  return m?.[1]?.trim() || null;
}

/** LLM fallback format: === FILE: open_fdd_data_model_import_ready.json === ... */
function extractImportJsonFromFileSections(text: string): unknown | null {
  const re = /^===\s*FILE:\s*([^\n]+?)\s*===\s*\n([\s\S]*?)(?=^===\s*FILE:|$)/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const name = m[1].trim().toLowerCase();
    const body = m[2].trim();
    if (!body) continue;
    const looksImport =
      name.includes("import_ready") || name.endsWith(".json") || name.includes("data_model_import");
    if (!looksImport) continue;
    try {
      return JSON.parse(body) as unknown;
    } catch {
      continue;
    }
  }
  return null;
}

function escapeBackslashesInLikelyPathFields(text: string): string {
  return text.replace(
    /"([\w.-]*(?:path|ref))"\s*:\s*"([^"]*)"/gi,
    (_full, key: string, value: string) => `"${key}":"${String(value).replace(/\\/g, "\\\\")}"`,
  );
}

function extractImportShape(parsed: unknown): unknown {
  if (parsed && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    if (obj.import_ready_json && typeof obj.import_ready_json === "object") {
      return obj.import_ready_json;
    }
    if (obj.proposed_model_json && typeof obj.proposed_model_json === "object") {
      return obj.proposed_model_json;
    }
  }
  return parsed;
}

function validateImportShape(value: unknown): ModelPayload {
  const obj = value as Record<string, unknown>;
  if (!obj || typeof obj !== "object") {
    throw new Error("Model payload must be an object.");
  }
  const sites = Array.isArray(obj.sites) ? obj.sites : null;
  const equipment = Array.isArray(obj.equipment) ? obj.equipment : null;
  const points = Array.isArray(obj.points) ? obj.points : null;
  if (!sites || !equipment || !points) {
    throw new Error("Model JSON must include arrays: sites, equipment, points.");
  }
  return {
    sites: sites as Array<Record<string, unknown>>,
    equipment: equipment as Array<Record<string, unknown>>,
    points: points as Array<Record<string, unknown>>,
  };
}
