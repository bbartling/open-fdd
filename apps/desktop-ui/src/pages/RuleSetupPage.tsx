import { useEffect, useRef, useState } from "react";
import { desktopFetchText } from "../lib/api";
import { useRulesList } from "../hooks/use-rules";
import { deleteRule, syncRuleDefinitions, uploadRule } from "../lib/crud-api";

export function RuleSetupPage() {
  const { data: rulesData, isLoading: rulesLoading, error: rulesError, refresh: refreshRules } = useRulesList();
  const [selectedFile, setSelectedFile] = useState("");
  const [selectedContent, setSelectedContent] = useState<string | null>(null);
  const [rulesStatus, setRulesStatus] = useState("Load a directory of YAML files, then view/delete as needed.");
  const directoryInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void refreshRules();
  }, []);

  async function openRule(filename: string) {
    try {
      setSelectedFile(filename);
      const text = await desktopFetchText(`/rules/${encodeURIComponent(filename)}`);
      setSelectedContent(text);
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function onLoadRuleDirectory(list: FileList | null) {
    if (!list || list.length === 0) {
      setRulesStatus("No files selected.");
      return;
    }
    const files = Array.from(list).filter(
      (f) => f.name.toLowerCase().endsWith(".yaml") || f.name.toLowerCase().endsWith(".yml"),
    );
    if (files.length === 0) {
      setRulesStatus("No YAML files found in selection.");
      return;
    }
    try {
      let uploaded = 0;
      for (const file of files) {
        const text = await file.text();
        await uploadRule(file.name, text);
        uploaded += 1;
      }
      setRulesStatus(`Loaded ${uploaded} YAML files from selected directory.`);
      await refreshRules();
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
        setSelectedContent(null);
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

  return (
    <div className="card">
      <h2 className="title">FDD Rule Setup</h2>

      <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <h3 className="title" style={{ marginBottom: 6 }}>FDD rule files (YAML)</h3>
        <p className="muted">Load a directory of YAML files, then click filenames to preview or delete.</p>
        {rulesError && <p style={{ color: "var(--danger)" }}>{rulesError}</p>}
        <p className="muted" style={{ marginTop: 8 }}>
          {rulesData?.rules_dir || "Loading rules directory..."}
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <button className="secondary-btn" onClick={() => void refreshRules()}>Refresh</button>
          <button className="secondary-btn" onClick={() => void onSyncDefinitions()}>Sync definitions</button>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              className="secondary-btn"
              aria-label="Load rules from directory"
              onClick={() => directoryInputRef.current?.click()}
            >
              Load rules from directory
            </button>
            <input
              ref={directoryInputRef}
              type="file"
              accept=".yaml,.yml,text/yaml,text/x-yaml"
              multiple
              style={{ display: "none" }}
              {...({ webkitdirectory: "", directory: "" } as unknown as Record<string, string>)}
              onChange={(e) => {
                void onLoadRuleDirectory(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
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
          {selectedContent ?? "Click a YAML filename to preview."}
        </div>
      </div>
    </div>
  );
}
