import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiFetchText } from "../lib/api";
import { DATA_MODEL_REDESIGN_PROMPT } from "../lib/llm-prompts";
import { ModelPayload, parseImportPayload } from "../lib/modelImport";
import PageHeader from "../components/PageHeader";
import RuleMappingBoard from "../components/RuleMappingBoard";

type SiteRow = { id: string; name: string };

export default function DataModelPage() {
  const [activeTab, setActiveTab] = useState<"mapping" | "model" | "advanced">("mapping");
  const [exportJsonText, setExportJsonText] = useState("");
  const [importJsonText, setImportJsonText] = useState("");
  const [out, setOut] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [ttlText, setTtlText] = useState("");
  const [copiedKey, setCopiedKey] = useState("");
  const [activeSiteId, setActiveSiteId] = useState("");
  const [pointCount, setPointCount] = useState(0);
  const [eqCount, setEqCount] = useState(0);

  const refreshMeta = useCallback(async () => {
    const [sitesRes, tree] = await Promise.all([
      apiFetch<{ active_site_id?: string; sites: SiteRow[] }>("/api/model/sites"),
      apiFetch<{ equipment: unknown[]; points: unknown[] }>("/api/model/tree"),
    ]);
    setActiveSiteId(sitesRes.active_site_id || sitesRes.sites?.[0]?.id || "");
    setPointCount(tree.points?.length ?? 0);
    setEqCount(tree.equipment?.length ?? 0);
  }, []);

  useEffect(() => {
    refreshMeta().catch((e) => setOut(String(e)));
  }, [refreshMeta]);

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
      await refreshMeta();
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
      setTtlText(await apiFetchText("/api/model/ttl?save=false", { headers: { Accept: "text/turtle" } }));
      setOut("Loaded TTL graph below.");
    } catch (error) {
      setTtlText("");
      setOut(`TTL view failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTtlLoading(false);
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Data Model BRICK"
        subtitle={
          <>
            Site <code>{activeSiteId || "…"}</code> is configured automatically · {eqCount} equipment · {pointCount}{" "}
            points
          </>
        }
      />

      <div className="tab-row">
        <button
          type="button"
          className={activeTab === "mapping" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("mapping")}
        >
          Rule mapping
        </button>
        <button
          type="button"
          className={activeTab === "model" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("model")}
        >
          Import / export
        </button>
        <button
          type="button"
          className={activeTab === "advanced" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("advanced")}
        >
          Advanced
        </button>
      </div>

      {activeTab === "mapping" ? (
        <RuleMappingBoard onStatus={(msg) => setOut(msg)} />
      ) : null}

      {activeTab === "model" ? (
        <>
          <div className="row">
            <button type="button" onClick={() => void doExport()}>
              Export JSON
            </button>
            <button type="button" onClick={() => void doImport()}>
              Import JSON
            </button>
            <label className="secondary-btn file-upload-btn">
              Upload JSON
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
          <textarea
            className="model-editor"
            value={importJsonText || exportJsonText}
            onChange={(e) => {
              if (importJsonText) setImportJsonText(e.target.value);
              else setExportJsonText(e.target.value);
            }}
            placeholder="Export to load JSON, or paste import payload here."
          />
        </>
      ) : null}

      {activeTab === "advanced" ? (
        <>
          <div className="row">
            <button type="button" className="secondary-btn" onClick={() => void copyText("prompt", DATA_MODEL_REDESIGN_PROMPT)}>
              {copiedKey === "prompt" ? "Copied Prompt" : "Copy LLM Prompt"}
            </button>
            <button type="button" onClick={() => void doViewTtl()}>
              {ttlLoading ? "Loading TTL…" : "View BRICK TTL"}
            </button>
          </div>
          <textarea readOnly className="ttl-editor" value={ttlText} placeholder="TTL appears after View BRICK TTL." />
        </>
      ) : null}

      <textarea readOnly className="status-line" value={out} />
    </div>
  );
}
