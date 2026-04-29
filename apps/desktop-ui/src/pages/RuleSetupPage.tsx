import { useEffect, useState } from "react";
import { desktopFetch, desktopFetchText } from "../lib/api";
import { useOptionalSite } from "../contexts/site-context";
import { useRulesList } from "../hooks/use-rules";
import { deleteRule, syncRuleDefinitions, uploadRule } from "../lib/crud-api";

type RuleDefaults = {
  rule_pack: string;
  source_dir: string;
  files: string[];
};

type RuleInstall = {
  rule_pack: string;
  rules_path: string;
  copied: string[];
};

type Site = { id: string; name: string };

export function RuleSetupPage() {
  const siteContext = useOptionalSite();
  const [defaults, setDefaults] = useState<RuleDefaults | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState(() => siteContext?.selectedSiteId ?? "");
  const [installedPath, setInstalledPath] = useState("");
  const [status, setStatus] = useState("Install default AHU/VAV YAML rules and attach rule pack to a site.");
  const { data: rulesData, isLoading: rulesLoading, error: rulesError, refresh: refreshRules } = useRulesList();
  const [selectedFile, setSelectedFile] = useState("");
  const [selectedContent, setSelectedContent] = useState("");
  const [uploadFilename, setUploadFilename] = useState("");
  const [uploadContent, setUploadContent] = useState("");
  const [rulesStatus, setRulesStatus] = useState("Upload/view/delete YAML files.");
  const [runSource, setRunSource] = useState("csv");
  const [chunkRows, setChunkRows] = useState("0");
  const [startTs, setStartTs] = useState("");
  const [endTs, setEndTs] = useState("");
  const [runOutput, setRunOutput] = useState("Use this panel to run/backfill FDD faults over a site/source/time window.");

  useEffect(() => {
    desktopFetch<RuleDefaults>("/rules/defaults")
      .then(setDefaults)
      .catch((e) => setStatus(e instanceof Error ? e.message : String(e)));
    desktopFetch<Site[]>("/sites")
      .then((s) => {
        setSites(s);
        if (s.length > 0 && !siteContext?.selectedSiteId) setSiteId(s[0].id);
      })
      .catch((e) => setStatus(e instanceof Error ? e.message : String(e)));
  }, []);

  async function installDefaults() {
    try {
      const out = await desktopFetch<RuleInstall>("/rules/defaults/install", { method: "POST" });
      setInstalledPath(out.rules_path);
      setStatus(`Installed ${out.copied.length} default rules to ${out.rules_path}`);
      await refreshRules();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function attachPackToSite() {
    const effectiveSiteId = siteId || siteContext?.selectedSiteId || "";
    if (!effectiveSiteId) return;
    try {
      const pack = defaults?.rule_pack ?? "ahu_vav";
      await desktopFetch(`/sites/${effectiveSiteId}/rule-pack`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule_pack: pack }),
      });
      const selectedSiteName = sites.find((s) => s.id === effectiveSiteId)?.name ?? "selected site";
      setStatus(`Attached rule pack '${pack}' to ${selectedSiteName} and synced TTL.`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function openRule(filename: string) {
    try {
      setSelectedFile(filename);
      const text = await desktopFetchText(`/rules/${encodeURIComponent(filename)}`);
      setSelectedContent(text);
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function onUploadRule() {
    const name = uploadFilename.trim();
    if (!name.endsWith(".yaml") && !name.endsWith(".yml")) {
      setRulesStatus("Filename must end with .yaml or .yml");
      return;
    }
    try {
      const out = await uploadRule(name, uploadContent);
      setRulesStatus(`Uploaded ${out.filename}`);
      setUploadFilename("");
      setUploadContent("");
      await refreshRules();
      await openRule(out.filename);
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function onDeleteRule(filename: string) {
    if (!window.confirm(`Delete rule file "${filename}"?`)) return;
    try {
      await deleteRule(filename);
      setRulesStatus(`Deleted ${filename}`);
      if (selectedFile === filename) {
        setSelectedFile("");
        setSelectedContent("");
      }
      await refreshRules();
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function onSyncDefinitions() {
    try {
      const out = await syncRuleDefinitions();
      setRulesStatus(`Synced definitions (${out.mode}, count=${out.synced}).`);
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function runRulesWindow() {
    try {
      const effectiveSiteId = siteId || siteContext?.selectedSiteId || "";
      if (!effectiveSiteId) {
        setRunOutput("Select a site first.");
        return;
      }
      const rulesPath = rulesData?.rules_dir || installedPath;
      if (!rulesPath) {
        setRunOutput("Rules directory is not ready yet. Install defaults or refresh rules.");
        return;
      }
      const parsedChunkRows = Number.parseInt(chunkRows || "0", 10);
      const safeChunkRows = Number.isFinite(parsedChunkRows) && parsedChunkRows >= 0 ? parsedChunkRows : 0;
      const out = await desktopFetch<{
        input_rows: number;
        output_rows: number;
        columns: string[];
        fault_totals: Record<string, number>;
        preview: string;
      }>("/rules/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          source: runSource,
          rules_path: rulesPath,
          chunk_rows: safeChunkRows,
          start_ts: startTs || null,
          end_ts: endTs || null,
        }),
      });
      setRunOutput(
        `Input rows: ${out.input_rows}\nOutput rows: ${out.output_rows}\n`
        + `Columns: ${out.columns.join(", ")}\n`
        + `Fault totals: ${JSON.stringify(out.fault_totals, null, 2)}\n\nPreview:\n${out.preview}`,
      );
    } catch (e) {
      setRunOutput(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">FDD Rule Setup</h2>
      <p style={{ color: "var(--muted)" }}>
        Step 1 after CSV import: install default AHU/VAV rules, then attach the rule pack to the site so TTL carries the rule-pack metadata for AI context.
      </p>
      <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
        <button onClick={() => void installDefaults()}>Install default AHU/VAV YAML rules</button>
        <button onClick={() => void attachPackToSite()}>Attach rule pack to selected site</button>
      </div>
      <div className="grid-two">
        <div>
          <label>Site</label>
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          {!siteId && siteContext?.selectedSiteId && (
            <small className="muted">Using selected site from top bar.</small>
          )}
        </div>
        <div>
          <label>Installed rules path</label>
          <input readOnly value={installedPath} placeholder="Not installed yet" />
        </div>
      </div>
      <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 80 }} />
      <textarea
        readOnly
        value={
          defaults
            ? `Default rule pack: ${defaults.rule_pack}\nSource: ${defaults.source_dir}\nFiles:\n${defaults.files.join("\n")}`
            : "Loading default rules..."
        }
        style={{ marginTop: 10, minHeight: 180 }}
      />

      <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <h3 className="title" style={{ marginBottom: 6 }}>Run / backfill faults</h3>
        <p className="muted">Run FDD rules on a selected source and optional time window for historical backfill.</p>
        <div className="grid-two">
          <div>
            <label>Source</label>
            <select value={runSource} onChange={(e) => setRunSource(e.target.value)}>
              <option value="csv">CSV</option>
              <option value="weather">Weather</option>
              <option value="onboard">Onboard</option>
              <option value="bacnet">BACnet</option>
            </select>
          </div>
          <div>
            <label>Chunk rows (0 = auto/full)</label>
            <input value={chunkRows} onChange={(e) => setChunkRows(e.target.value)} placeholder="0" />
          </div>
          <div>
            <label>Start timestamp (optional, ISO)</label>
            <input value={startTs} onChange={(e) => setStartTs(e.target.value)} placeholder="2026-03-01T00:00:00Z" />
          </div>
          <div>
            <label>End timestamp (optional, ISO)</label>
            <input value={endTs} onChange={(e) => setEndTs(e.target.value)} placeholder="2026-03-31T23:59:59Z" />
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <button onClick={() => void runRulesWindow()}>Run FDD backfill</button>
        </div>
        <textarea readOnly value={runOutput} style={{ marginTop: 10, minHeight: 180 }} />
      </div>

      <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <h3 className="title" style={{ marginBottom: 6 }}>FDD rule files (YAML)</h3>
        <p className="muted">Choose file, upload, sync definitions, click filename to view, or delete.</p>
        {rulesError && <p style={{ color: "var(--danger)" }}>{rulesError}</p>}
        <p className="muted" style={{ marginTop: 8 }}>
          {rulesData?.rules_dir || "Loading rules directory..."}
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <button className="secondary-btn" onClick={() => void refreshRules()}>Refresh</button>
          <button className="secondary-btn" onClick={() => void onSyncDefinitions()}>Sync definitions</button>
          <button className="secondary-btn" onClick={() => void installDefaults()}>Install default AHU/VAV rules</button>
        </div>

        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {rulesLoading && <span className="muted">Loading files...</span>}
          {(rulesData?.files ?? []).map((name) => (
            <span key={name} style={{ display: "inline-flex", gap: 6, alignItems: "center", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 8px" }}>
              <button className="secondary-btn" style={{ border: 0, background: "transparent", padding: 0 }} onClick={() => void openRule(name)}>
                {name}
              </button>
              <button className="danger-btn" style={{ padding: "2px 8px" }} onClick={() => void onDeleteRule(name)}>Delete</button>
            </span>
          ))}
        </div>

        <div className="grid-two" style={{ marginTop: 10 }}>
          <input value={uploadFilename} onChange={(e) => setUploadFilename(e.target.value)} placeholder="filename.yaml" />
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span className="secondary-btn" style={{ padding: "8px 12px", cursor: "pointer" }}>Choose file</span>
            <input
              type="file"
              accept=".yaml,.yml,text/yaml,text/x-yaml"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setUploadFilename(file.name);
                const reader = new FileReader();
                reader.onload = () => setUploadContent(String(reader.result ?? ""));
                reader.readAsText(file);
                e.target.value = "";
              }}
            />
          </label>
        </div>
        <textarea
          value={uploadContent}
          onChange={(e) => setUploadContent(e.target.value)}
          placeholder="Paste YAML or choose file..."
          style={{ marginTop: 10, minHeight: 150, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}
        />
        <div style={{ marginTop: 8 }}>
          <button onClick={() => void onUploadRule()}>Upload</button>
        </div>
        <textarea readOnly value={rulesStatus} style={{ marginTop: 10, minHeight: 70 }} />
        <div
          style={{
            marginTop: 10,
            minHeight: 420,
            padding: 12,
            border: "1px solid var(--border)",
            borderRadius: 10,
            background: "var(--input-bg)",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            whiteSpace: "pre-wrap",
            overflowX: "auto",
          }}
        >
          {selectedContent || "Click a YAML filename to preview."}
        </div>
      </div>
    </div>
  );
}
