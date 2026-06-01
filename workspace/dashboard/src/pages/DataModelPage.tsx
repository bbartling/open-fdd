import { useCallback, useEffect, useState } from "react";
import { apiFetchText } from "../lib/api";
import { openTtlPopup, openTextPopup } from "../lib/ttlPopup";
import { copyToClipboard } from "../lib/clipboard";
import { buildLlmModelBundle } from "../lib/llmModelBundle";
import { DATA_MODEL_REDESIGN_PROMPT } from "../lib/llm-prompts";
import { ModelPayload } from "../lib/modelImport";
import ModelGraphExplorer from "../components/ModelGraphExplorer";
import ModelImportExportPanel from "../components/ModelImportExportPanel";
import ModelSyncBar from "../components/ModelSyncBar";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";

type SiteRow = { id: string; name: string };

export default function DataModelPage() {
  const [activeTab, setActiveTab] = useState<"explorer" | "import" | "advanced">("explorer");
  const [out, setOut] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [copiedKey, setCopiedKey] = useState("");
  const [activeSiteId, setActiveSiteId] = useState("");
  const [pointCount, setPointCount] = useState(0);
  const [eqCount, setEqCount] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const refreshMeta = useCallback(async () => {
    const [sitesRes, tree] = await Promise.all([
      apiFetch<{ active_site_id?: string; sites: SiteRow[] }>("/api/model/sites"),
      apiFetch<{ equipment: unknown[]; points: unknown[] }>("/api/model/tree"),
    ]);
    setActiveSiteId(sitesRes.active_site_id || sitesRes.sites?.[0]?.id || "");
    setPointCount(tree.points?.length ?? 0);
    setEqCount(tree.equipment?.length ?? 0);
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    refreshMeta().catch((e) => setOut(String(e)));
  }, [refreshMeta]);

  const [copyBusy, setCopyBusy] = useState(false);

  async function copyForLlm() {
    setCopyBusy(true);
    try {
      const model = await apiFetch<ModelPayload>("/api/model/export");
      await copyToClipboard(buildLlmModelBundle(DATA_MODEL_REDESIGN_PROMPT, model));
      setCopiedKey("llm");
      window.setTimeout(() => setCopiedKey(""), 2000);
      setOut("Copied LLM prompt + current model JSON — paste into your chat session.");
    } catch (error) {
      setOut(`Copy failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setCopyBusy(false);
    }
  }

  async function doViewTtlPopup() {
    setTtlLoading(true);
    try {
      const err = await openTtlPopup(() =>
        apiFetchText("/api/model/ttl?save=false", { headers: { Accept: "text/turtle" } }),
      );
      if (err) setOut(`TTL: ${err}`);
      else setOut("Opened BRICK TTL in a new browser tab.");
    } finally {
      setTtlLoading(false);
    }
  }

  async function doViewJsonPopup() {
    try {
      const text = JSON.stringify(await apiFetch("/api/model/export"), null, 2);
      if (!openTextPopup("model.json", text)) {
        setOut("Popup blocked — allow popups to view raw model JSON.");
        return;
      }
      setOut("Opened model JSON in a new browser tab.");
    } catch (error) {
      setOut(`JSON view failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Data Model BRICK"
        subtitle={
          <>
            Site <code>{activeSiteId || "…"}</code> · {eqCount} equipment · {pointCount} points · poll CSV,{" "}
            <code>model.json</code>, and TTL stay aligned via sync
          </>
        }
      />

      <div className="tab-row">
        <button
          type="button"
          className={activeTab === "explorer" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("explorer")}
        >
          Explorer
        </button>
        <button
          type="button"
          className={activeTab === "import" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("import")}
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

      {activeTab === "explorer" ? (
        <>
          <ModelSyncBar refreshKey={refreshKey} onStatus={setOut} />
          <ModelGraphExplorer
            refreshKey={refreshKey}
            onStatus={setOut}
            onModelChange={() => void refreshMeta()}
          />
        </>
      ) : null}

      {activeTab === "import" ? (
        <ModelImportExportPanel
          onStatus={setOut}
          onImported={() => void refreshMeta()}
        />
      ) : null}

      {activeTab === "advanced" ? (
        <div className="dm-advanced panel">
          <p className="muted">
            <strong>Copy prompt + model for LLM</strong> bundles the redesign instructions with your live export (sites,
            equipment, points) in one paste block. Works on HTTP LAN hosts without the Clipboard API.
          </p>
          <div className="row">
            <button type="button" onClick={() => void doViewTtlPopup()}>
              {ttlLoading ? "Loading TTL…" : "View TTL (new tab)"}
            </button>
            <button type="button" className="secondary-btn" onClick={() => void doViewJsonPopup()}>
              View model JSON (new tab)
            </button>
            <button type="button" className="secondary-btn" disabled={copyBusy} onClick={() => void copyForLlm()}>
              {copiedKey === "llm" ? "Copied for LLM" : copyBusy ? "Copying…" : "Copy prompt + model for LLM"}
            </button>
          </div>
          <details className="dm-prompt-details">
            <summary>LLM prompt preview</summary>
            <textarea readOnly className="dm-json-editor dm-prompt-preview" value={DATA_MODEL_REDESIGN_PROMPT} />
          </details>
        </div>
      ) : null}

      {out ? (
        <div className="status-bar" role="status">
          {out}
        </div>
      ) : null}
    </div>
  );
}
