import { useCallback, useEffect, useState } from "react";
import { apiFetchText } from "../lib/api";
import { openTtlPopup, openTextPopup } from "../lib/ttlPopup";
import { copyToClipboard } from "../lib/clipboard";
import { buildLlmCommissioningBundle } from "../lib/llmModelBundle";
import { MODEL_COMMISSIONING_PROMPT } from "../lib/llm-prompts";
import { assignmentSummary, parseCommissioningPayload } from "../lib/commissioningImport";
import DataModelSparqlPanel from "../components/DataModelSparqlPanel";
import CommissioningImportExportPanel from "../components/CommissioningImportExportPanel";
import ModelSyncBar from "../components/ModelSyncBar";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";

type SiteRow = { id: string; name: string };

export default function DataModelPage() {
  const [activeTab, setActiveTab] = useState<"explorer" | "import" | "sparql" | "advanced">("import");
  const [out, setOut] = useState("");
  const [ttlLoading, setTtlLoading] = useState(false);
  const [copiedKey, setCopiedKey] = useState("");
  const [activeSiteId, setActiveSiteId] = useState("");
  const [pointCount, setPointCount] = useState(0);
  const [eqCount, setEqCount] = useState(0);
  const [ruleCount, setRuleCount] = useState(0);
  const [boundPoints, setBoundPoints] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const refreshMeta = useCallback(async () => {
    const [sitesRes, tree, bundle] = await Promise.all([
      apiFetch<{ active_site_id?: string; sites: SiteRow[] }>("/api/model/sites"),
      apiFetch<{ equipment: unknown[]; points: unknown[] }>("/api/model/tree"),
      apiFetch<Record<string, unknown>>("/api/model/commissioning-export"),
    ]);
    setActiveSiteId(sitesRes.active_site_id || sitesRes.sites?.[0]?.id || "");
    setPointCount(tree.points?.length ?? 0);
    setEqCount(tree.equipment?.length ?? 0);
    const summary = assignmentSummary(parseCommissioningPayload(JSON.stringify(bundle)));
    setRuleCount(summary.ruleCount);
    setBoundPoints(summary.boundPointCount);
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    refreshMeta().catch((e) => setOut(String(e)));
  }, [refreshMeta]);

  useEffect(() => {
    const onChange = () => void refreshMeta();
    window.addEventListener("ofdd-assignments-changed", onChange);
    return () => window.removeEventListener("ofdd-assignments-changed", onChange);
  }, [refreshMeta]);

  const [copyBusy, setCopyBusy] = useState(false);

  async function copyForLlm() {
    setCopyBusy(true);
    try {
      const bundle = await apiFetch<Record<string, unknown>>("/api/model/commissioning-export");
      await copyToClipboard(buildLlmCommissioningBundle(MODEL_COMMISSIONING_PROMPT, bundle));
      setCopiedKey("llm");
      window.setTimeout(() => setCopiedKey(""), 2000);
      setOut("Copied LLM prompt + commissioning JSON (BRICK + FDD assignments) — paste into your chat session.");
    } catch (error) {
      setOut(`Copy failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setCopyBusy(false);
    }
  }

  async function syncTtlDisk() {
    setTtlLoading(true);
    try {
      const res = await apiFetch<{ path: string }>("/api/model/sync-ttl", { method: "POST" });
      setOut(`TTL written to ${res.path}`);
    } catch (error) {
      setOut(`TTL sync failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTtlLoading(false);
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
      const text = JSON.stringify(await apiFetch("/api/model/commissioning-export"), null, 2);
      if (!openTextPopup("openfdd-commissioning.json", text)) {
        setOut("Popup blocked — allow popups to view commissioning JSON.");
        return;
      }
      setOut("Opened commissioning JSON in a new browser tab.");
    } catch (error) {
      setOut(`JSON view failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Model & FDD assignments"
        subtitle={
          <>
            Site <code>{activeSiteId || "…"}</code> · {eqCount} equipment · {pointCount} points · {ruleCount} rules ·{" "}
            {boundPoints} bound points · edit BRICK + rule pins via commissioning JSON (Import / export tab)
          </>
        }
      />

      <div className="tab-row">
        <button
          type="button"
          className={activeTab === "import" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("import")}
        >
          Import / export
        </button>
        <button
          type="button"
          className={activeTab === "explorer" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("explorer")}
        >
          Explorer
        </button>
        <button
          type="button"
          className={activeTab === "sparql" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("sparql")}
        >
          SPARQL
        </button>
        <button
          type="button"
          className={activeTab === "advanced" ? "" : "secondary-btn"}
          onClick={() => setActiveTab("advanced")}
        >
          Advanced
        </button>
      </div>

      {activeTab === "import" ? (
        <CommissioningImportExportPanel
          onStatus={setOut}
          onImported={() => void refreshMeta()}
        />
      ) : null}

      {activeTab === "explorer" ? (
        <>
          <ModelSyncBar refreshKey={refreshKey} onStatus={setOut} showWriteTtl={false} />
          <p className="muted panel">
            BACnet poll → model sync keeps <code>model.json</code> aligned with live polling. Pin FDD rules via{" "}
            <strong>Import / export</strong> or Rule Lab equipment test. RDF / TTL tools are on <strong>SPARQL</strong>{" "}
            and <strong>Advanced</strong>.
          </p>
        </>
      ) : null}

      {activeTab === "sparql" ? <DataModelSparqlPanel onStatus={setOut} /> : null}

      {activeTab === "advanced" ? (
        <div className="dm-advanced panel">
          <p className="muted">
            <strong>Copy prompt + commissioning JSON for LLM</strong> bundles BRICK redesign instructions with live
            export including <code>fdd_rules</code> and per-point <code>fdd_rule_ids</code>. Rule Lab owns Python code —
            the LLM only edits model JSON and rule assignments.
          </p>
          <div className="row">
            <button type="button" onClick={() => void doViewTtlPopup()}>
              {ttlLoading ? "Loading TTL…" : "View TTL (new tab)"}
            </button>
            <button type="button" className="secondary-btn" disabled={ttlLoading} onClick={() => void syncTtlDisk()}>
              {ttlLoading ? "Writing TTL…" : "Write TTL to disk"}
            </button>
            <button type="button" className="secondary-btn" onClick={() => void doViewJsonPopup()}>
              View commissioning JSON (new tab)
            </button>
            <button type="button" className="secondary-btn" disabled={copyBusy} onClick={() => void copyForLlm()}>
              {copiedKey === "llm" ? "Copied for LLM" : copyBusy ? "Copying…" : "Copy prompt + JSON for LLM"}
            </button>
          </div>
          <details className="dm-prompt-details">
            <summary>LLM prompt preview</summary>
            <textarea readOnly className="dm-json-editor dm-prompt-preview" value={MODEL_COMMISSIONING_PROMPT} />
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
