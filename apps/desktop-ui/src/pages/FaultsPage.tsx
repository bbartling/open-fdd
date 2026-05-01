import { useEffect, useMemo, useState } from "react";
import { desktopFetch, desktopFetchText } from "../lib/api";
import { useOptionalSite } from "../contexts/site-context";

type RuleResponse = {
  input_rows: number;
  output_rows: number;
  columns: string[];
  fault_totals: Record<string, number>;
  preview: string;
  rule_files_filter?: string[] | null;
  skip_missing_columns?: boolean;
};

type RulesListResponse = {
  rules_dir: string;
  files: string[];
};

type RuleDefaultsInstallResponse = {
  rule_pack: string;
  rules_path: string;
  copied: string[];
};

export function FaultsPage() {
  const siteContext = useOptionalSite();
  const [siteId, setSiteId] = useState(() => siteContext?.selectedSiteId ?? "");
  const [source, setSource] = useState("csv");
  const [rulesPath, setRulesPath] = useState("");
  const [chunkRows, setChunkRows] = useState("0");
  const [output, setOutput] = useState("");
  const [rulesDir, setRulesDir] = useState("");
  const [ruleFiles, setRuleFiles] = useState<string[]>([]);
  const [selectedRule, setSelectedRule] = useState("");
  const [selectedRuleContent, setSelectedRuleContent] = useState("");
  const [ruleFilename, setRuleFilename] = useState("");
  const [ruleContent, setRuleContent] = useState("");
  const [ruleStatus, setRuleStatus] = useState("Load, view, upload, and delete rule YAML files.");
  const [backfillRuleFiles, setBackfillRuleFiles] = useState<string[]>([]);
  const [skipMissingRules, setSkipMissingRules] = useState(false);

  const effectiveRulesPath = useMemo(() => rulesPath || rulesDir, [rulesPath, rulesDir]);

  /** Rule file list comes from GET /rules (managed ``rules_dir``). Only allow a filter when the run path matches that directory. */
  const ruleFilesFilterMatchesRun = useMemo(() => {
    if (!rulesDir.trim()) return false;
    const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/u, "").toLowerCase();
    return norm(effectiveRulesPath) === norm(rulesDir);
  }, [effectiveRulesPath, rulesDir]);

  async function refreshRuleFiles() {
    try {
      const out = await desktopFetch<RulesListResponse>("/rules");
      setRulesDir(out.rules_dir);
      setRuleFiles(out.files);
      if (!rulesPath) {
        setRulesPath(out.rules_dir);
      }
      setBackfillRuleFiles((prev) => {
        const next = prev.filter((f) => out.files.includes(f));
        const runPath = (rulesPath || out.rules_dir).trim() || out.rules_dir.trim();
        const sameDir = runPath.replace(/\\/g, "/").replace(/\/+$/u, "").toLowerCase()
          === out.rules_dir.replace(/\\/g, "/").replace(/\/+$/u, "").toLowerCase();
        return sameDir ? next : [];
      });
      if (selectedRule && !out.files.includes(selectedRule)) {
        setSelectedRule("");
        setSelectedRuleContent("");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuleStatus(`Failed to load rule files: ${message}`);
    }
  }

  useEffect(() => {
    if (!ruleFilesFilterMatchesRun) {
      setBackfillRuleFiles([]);
    }
  }, [ruleFilesFilterMatchesRun]);

  async function runRules() {
    try {
      const effectiveSiteId = siteId || siteContext?.selectedSiteId || "";
      const ruleFilesArg =
        ruleFilesFilterMatchesRun && backfillRuleFiles.length > 0
          ? backfillRuleFiles.filter((f) => ruleFiles.includes(f))
          : undefined;
      const out = await desktopFetch<RuleResponse>("/rules/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          source,
          rules_path: effectiveRulesPath,
          chunk_rows: Number(chunkRows || "0"),
          rule_files: ruleFilesArg,
          skip_missing_columns: skipMissingRules,
        }),
      });
      const head = out.rule_files_filter?.length
        ? `Rule files: ${out.rule_files_filter.join(", ")}\n`
        : "Rule files: (all in directory)\n";
      const skip = `Skip missing columns: ${out.skip_missing_columns ? "yes" : "no"}\n`;
      setOutput(
        `${head}${skip}\n` +
          `Input rows: ${out.input_rows}\nOutput rows: ${out.output_rows}\n` +
          `Columns: ${out.columns.join(", ")}\nFault totals: ${JSON.stringify(out.fault_totals, null, 2)}\n\nPreview:\n${out.preview}`,
      );
    } catch (error) {
      console.error("runRules failed", error);
      const message = error instanceof Error ? error.message : String(error);
      setOutput(`Error running rules: ${message}`);
    }
  }

  async function openRuleFile(filename: string) {
    try {
      const text = await desktopFetchText(`/rules/${encodeURIComponent(filename)}`);
      setSelectedRule(filename);
      setSelectedRuleContent(text);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuleStatus(`Failed to open ${filename}: ${message}`);
    }
  }

  async function uploadRule() {
    const name = ruleFilename.trim();
    if (!name) {
      setRuleStatus("Provide a .yaml filename.");
      return;
    }
    try {
      const out = await desktopFetch<{ filename: string }>("/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: name, content: ruleContent }),
      });
      setRuleStatus(`Uploaded ${out.filename}`);
      setRuleFilename(out.filename);
      setRuleContent("");
      await refreshRuleFiles();
      await openRuleFile(out.filename);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuleStatus(`Upload failed: ${message}`);
    }
  }

  async function deleteRule(filename: string) {
    if (!window.confirm(`Delete rule file "${filename}"?`)) return;
    try {
      await desktopFetch(`/rules/${encodeURIComponent(filename)}`, { method: "DELETE" });
      setRuleStatus(`Deleted ${filename}`);
      await refreshRuleFiles();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuleStatus(`Delete failed: ${message}`);
    }
  }

  async function syncDefinitions() {
    try {
      const out = await desktopFetch<{ synced: number; mode: string }>("/rules/sync-definitions", {
        method: "POST",
      });
      setRuleStatus(`Synced definitions (${out.mode}, count=${out.synced}).`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuleStatus(`Sync failed: ${message}`);
    }
  }

  async function installDefaultRules() {
    try {
      const out = await desktopFetch<RuleDefaultsInstallResponse>("/rules/defaults/install", {
        method: "POST",
      });
      setRuleStatus(`Installed ${out.copied.length} default rules to ${out.rules_path}`);
      await refreshRuleFiles();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuleStatus(`Install defaults failed: ${message}`);
    }
  }

  useEffect(() => {
    void refreshRuleFiles();
  }, []);

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Faults</h2>
        <div className="grid-two">
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site id" />
          {!siteId && siteContext?.selectedSiteId && (
          <small className="muted">Using selected site from top bar.</small>
          )}
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="source" />
          <input value={rulesPath} onChange={(e) => setRulesPath(e.target.value)} placeholder="rules path directory" />
          <input value={chunkRows} onChange={(e) => setChunkRows(e.target.value)} placeholder="chunk rows" />
        </div>
        {ruleFiles.length > 0 ? (
          <div style={{ marginTop: 10 }}>
            <label>Run only these rule files (optional)</label>
            <select
              multiple
              disabled={!ruleFilesFilterMatchesRun}
              value={backfillRuleFiles}
              onChange={(e) => setBackfillRuleFiles(Array.from(e.target.selectedOptions).map((o) => o.value))}
              style={{ minHeight: 90, width: "100%", maxWidth: 520 }}
            >
              {ruleFiles.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
            {!ruleFilesFilterMatchesRun ? (
              <p className="muted" style={{ marginTop: 6, marginBottom: 0, fontSize: 12 }}>
                File filter is disabled when the rules path above does not match the managed rules directory (list is for that directory only).
              </p>
            ) : null}
          </div>
        ) : null}
        <label style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 10 }}>
          <input
            style={{ width: "auto" }}
            type="checkbox"
            checked={skipMissingRules}
            onChange={(e) => setSkipMissingRules(e.target.checked)}
          />
          Skip rules with missing columns
        </label>
        <div style={{ marginTop: 12 }}>
          <button onClick={() => void runRules()}>Run Rules</button>
        </div>
        <textarea readOnly value={output} style={{ marginTop: 12, minHeight: 260 }} />
      </div>

      <div className="card">
        <h3 className="title">FDD Rule Files (YAML)</h3>
        <p className="muted">AFDD-style workflow: list, open, upload, sync, and delete rule files.</p>
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          <button onClick={() => void refreshRuleFiles()}>Refresh files</button>
          <button className="secondary-btn" onClick={() => void installDefaultRules()}>Install default AHU/VAV rules</button>
          <button className="secondary-btn" onClick={() => void syncDefinitions()}>Sync definitions</button>
          <span className="muted" style={{ alignSelf: "center" }}>{rulesDir || "rules directory not loaded"}</span>
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
          {ruleFiles.map((name) => (
            <span key={name} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid var(--border)", borderRadius: 8, padding: "4px 8px", background: "var(--panel-soft)" }}>
              <button
                className="secondary-btn"
                style={{ padding: "4px 8px", border: 0, background: "transparent" }}
                onClick={() => void openRuleFile(name)}
              >
                {name}
              </button>
              <button className="danger-btn" style={{ padding: "3px 8px" }} onClick={() => void deleteRule(name)}>Delete</button>
            </span>
          ))}
          {ruleFiles.length === 0 && <span className="muted">No .yaml files found.</span>}
        </div>
        <textarea readOnly value={selectedRuleContent} placeholder="Select a YAML file to view its contents." style={{ minHeight: 180, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }} />
        <div className="grid-two" style={{ marginTop: 10 }}>
          <input value={ruleFilename} onChange={(e) => setRuleFilename(e.target.value)} placeholder="new filename.yaml" />
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span className="secondary-btn" style={{ padding: "8px 12px", cursor: "pointer" }}>Choose .yaml file</span>
            <input
              type="file"
              accept=".yaml,.yml,text/yaml,text/x-yaml"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setRuleFilename(file.name.endsWith(".yaml") || file.name.endsWith(".yml") ? file.name : `${file.name}.yaml`);
                const reader = new FileReader();
                reader.onload = () => setRuleContent(String(reader.result ?? ""));
                reader.readAsText(file);
                e.target.value = "";
              }}
            />
          </label>
        </div>
        <textarea value={ruleContent} onChange={(e) => setRuleContent(e.target.value)} placeholder="Paste YAML content here or choose a file above." style={{ marginTop: 10, minHeight: 180, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }} />
        <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
          <button onClick={() => void uploadRule()}>Upload YAML</button>
        </div>
        <textarea readOnly value={ruleStatus} style={{ marginTop: 10, minHeight: 70 }} />
      </div>
    </div>
  );
}
