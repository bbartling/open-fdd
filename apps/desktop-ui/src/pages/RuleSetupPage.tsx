import { useEffect, useRef, useState } from "react";
import { desktopFetchText } from "../lib/api";
import { useRulesList } from "../hooks/use-rules";
import { deleteRule, saveRule, uploadRule } from "../lib/crud-api";

export function RuleSetupPage() {
  const { data: rulesData, isLoading: rulesLoading, error: rulesError, refresh: refreshRules } = useRulesList();
  const [selectedFile, setSelectedFile] = useState("");
  const [selectedContent, setSelectedContent] = useState<string | null>(null);
  const lastSyncedContent = useRef<string | null>(null);
  const [rulesStatus, setRulesStatus] = useState(
    "Mass-load every YAML under one folder, or pick one-or-more files. Then click a name to edit.",
  );
  const directoryInputRef = useRef<HTMLInputElement | null>(null);
  /** Multi-file picker (no webkitdirectory): use when the folder picker drops YAML (e.g. accept + directory quirk). */
  const yamlFilesInputRef = useRef<HTMLInputElement | null>(null);

  const dirty =
    Boolean(selectedFile) &&
    selectedContent !== null &&
    lastSyncedContent.current !== null &&
    selectedContent !== lastSyncedContent.current;

  useEffect(() => {
    void refreshRules();
  }, []);

  async function openRule(filename: string) {
    try {
      const text = await desktopFetchText(`/rules/${encodeURIComponent(filename)}`);
      setSelectedFile(filename);
      setSelectedContent(text);
      lastSyncedContent.current = text;
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function onSaveRule() {
    if (!selectedFile || selectedContent == null) return;
    try {
      await saveRule(selectedFile, selectedContent);
      lastSyncedContent.current = selectedContent;
      setRulesStatus(`Saved ${selectedFile}`);
      await refreshRules();
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  function onDiscardEdits() {
    if (lastSyncedContent.current !== null) {
      setSelectedContent(lastSyncedContent.current);
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
      const basenameCounts = new Map<string, number>();
      for (const file of files) {
        basenameCounts.set(file.name, (basenameCounts.get(file.name) ?? 0) + 1);
      }
      const duplicateBasenames = Array.from(basenameCounts.entries())
        .filter(([, count]) => count > 1)
        .map(([name]) => name);
      const uploadNameCounts = new Map<string, number>();
      for (const file of files) {
        const sourceId = (file.webkitRelativePath || file.name).replaceAll("\\", "/");
        const baseUploadName = sourceId.replaceAll("/", "__");
        const keyCount = (uploadNameCounts.get(baseUploadName) ?? 0) + 1;
        uploadNameCounts.set(baseUploadName, keyCount);
        const uploadName = keyCount > 1
          ? `${baseUploadName.replace(/(\.[^.]+)?$/, (_m, ext = "") => `-${keyCount}${ext}`)}`
          : baseUploadName;
        const text = await file.text();
        await uploadRule(uploadName, text);
        uploaded += 1;
      }
      if (duplicateBasenames.length > 0) {
        setRulesStatus(
          `Loaded ${uploaded} YAML files. Duplicate basenames detected and disambiguated: ${duplicateBasenames.join(", ")}`,
        );
      } else {
        setRulesStatus(`Loaded ${uploaded} YAML files from selected directory.`);
      }
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
        lastSyncedContent.current = null;
      }
      await refreshRules();
    } catch (e) {
      setRulesStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">FDD Rule Setup</h2>

      <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <h3 className="title" style={{ marginBottom: 6 }}>FDD rule files (YAML)</h3>
        <p className="muted">
          <strong>Mass-load from folder</strong> walks one directory tree and uploads every <code>.yaml</code> /{" "}
          <code>.yml</code> in one go. <strong>Add YAML file(s)…</strong> opens a normal file dialog so you can add one
          file or multi-select many (same upload path). Click a name to open the editor; Save writes the files the
          bridge serves under <code className="muted">rules_dir</code>. Assistants can use{" "}
          <code className="muted">GET /rules/export-json</code> and <code className="muted">PUT /rules/&lt;file&gt;</code>.
        </p>
        <p className="muted" style={{ fontSize: "0.92em" }}>
          Desktop bridge: rules are read directly from disk after upload — there is no separate &quot;sync definitions&quot;
          step. Use <strong>Refresh</strong> to reload the file list.
        </p>
        {rulesError && <p style={{ color: "var(--danger)" }}>{rulesError}</p>}
        <p className="muted" style={{ marginTop: 8 }}>
          {rulesData?.rules_dir || "Loading rules directory..."}
        </p>
        <p className="muted" style={{ marginTop: 6, fontSize: "0.92em" }}>
          Folder tip: choose the directory that <strong>contains</strong> the YAML files (often a <code>rules</code>{" "}
          subfolder). If the folder picker returns no files (browser quirk), use <strong>Add YAML file(s)…</strong> and
          multi-select from that folder instead.
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <button className="secondary-btn" onClick={() => void refreshRules()}>Refresh</button>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              className="secondary-btn"
              aria-label="Mass-load all YAML files from one directory"
              onClick={() => directoryInputRef.current?.click()}
            >
              Mass-load YAML from folder
            </button>
            <input
              ref={directoryInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              {...({ webkitdirectory: "", directory: "" } as unknown as Record<string, string>)}
              onChange={(e) => {
                void onLoadRuleDirectory(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              className="secondary-btn"
              aria-label="Add one or more YAML files from a file picker"
              onClick={() => yamlFilesInputRef.current?.click()}
            >
              Add YAML file(s)…
            </button>
            <input
              ref={yamlFilesInputRef}
              type="file"
              accept=".yaml,.yml,text/yaml,text/x-yaml,application/x-yaml"
              multiple
              style={{ display: "none" }}
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
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button
            type="button"
            className="secondary-btn"
            disabled={!selectedFile || !dirty}
            onClick={() => void onSaveRule()}
          >
            Save YAML
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={!selectedFile || !dirty}
            onClick={onDiscardEdits}
          >
            Discard edits
          </button>
          {dirty ? <span className="muted">Unsaved changes</span> : selectedFile ? <span className="muted">Saved</span> : null}
        </div>
        <textarea
          value={selectedContent ?? ""}
          readOnly={!selectedFile}
          spellCheck={false}
          onChange={(e) => {
            if (!selectedFile) return;
            setSelectedContent(e.target.value);
          }}
          placeholder="Click a YAML filename to open the editor."
          style={{
            marginTop: 10,
            width: "100%",
            minHeight: 420,
            boxSizing: "border-box",
            padding: 12,
            border: "1px solid var(--border)",
            borderRadius: 10,
            background: "var(--input-bg)",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            whiteSpace: "pre",
            overflowX: "auto",
          }}
        />
      </div>
    </div>
  );
}
