import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import {
  assignmentSummary,
  type CommissioningPayload,
  parseCommissioningPayload,
} from "../lib/commissioningImport";

type Props = {
  onStatus: (msg: string) => void;
  onImported?: () => void;
};

export default function CommissioningImportExportPanel({ onStatus, onImported }: Props) {
  const [exportText, setExportText] = useState("");
  const [importText, setImportText] = useState("");
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const loadExport = useCallback(async () => {
    setExportLoading(true);
    try {
      const bundle = await apiFetch<CommissioningPayload>("/api/model/commissioning-export");
      setExportText(JSON.stringify(bundle, null, 2));
    } catch (error) {
      onStatus(`Export failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setExportLoading(false);
    }
  }, [onStatus]);

  useEffect(() => {
    void loadExport();
  }, [loadExport]);

  const exportSummary = useMemo(() => {
    if (!exportText.trim()) return null;
    try {
      return assignmentSummary(parseCommissioningPayload(exportText));
    } catch {
      return null;
    }
  }, [exportText]);

  async function doImport() {
    if (!importText.trim()) {
      onStatus("Paste commissioning JSON in the import box first (or upload a file).");
      return;
    }
    try {
      const payload = parseCommissioningPayload(importText);
      const confirmed = window.confirm(
        "Import replaces sites, equipment, and points, then applies FDD rule bindings from fdd_rules and points[].fdd_rule_ids. Continue?",
      );
      if (!confirmed) {
        onStatus("Import canceled.");
        return;
      }
      setImportLoading(true);
      const resp = await apiFetch<{
        sites: number;
        equipment: number;
        points: number;
        fdd_rules_updated?: number;
        fdd_bound_point_refs?: number;
      }>("/api/model/commissioning-import", {
        method: "POST",
        body: JSON.stringify({ payload, replace: true }),
      });
      onStatus(
        `Imported sites=${resp.sites}, equipment=${resp.equipment}, points=${resp.points}; ` +
          `FDD rules updated=${resp.fdd_rules_updated ?? 0}, bound point refs=${resp.fdd_bound_point_refs ?? 0}.`,
      );
      setImportText("");
      await loadExport();
      onImported?.();
      window.dispatchEvent(new CustomEvent("ofdd-assignments-changed"));
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
    a.download = "openfdd-commissioning.json";
    a.click();
    URL.revokeObjectURL(url);
    onStatus("Downloaded openfdd-commissioning.json");
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
          <h3 className="panel-title">Export commissioning JSON</h3>
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
          Includes <code>sites</code>, <code>equipment</code>, <code>points</code> (with optional{" "}
          <code>fdd_rule_ids</code> per point), and <code>fdd_rules[]</code> binding summary. Paste into your AI
          session or edit by hand — then import the same file to apply Haystack + assignments together.
        </p>
        {exportSummary ? (
          <p className="muted">
            <strong>{exportSummary.ruleCount}</strong> saved rules · <strong>{exportSummary.boundPointCount}</strong>{" "}
            points with pins · <strong>{exportSummary.pointsWithRules}</strong> points tagged via{" "}
            <code>fdd_rule_ids</code>
          </p>
        ) : null}
        <textarea
          readOnly
          className="dm-json-editor"
          value={exportText}
          placeholder="Click Refresh to load Haystack model + FDD assignments…"
        />
      </section>

      <section className="dm-io-panel panel">
        <header className="dm-io-head">
          <h3 className="panel-title">Import commissioning JSON</h3>
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
          Edit assignments by setting <code>points[].fdd_rule_ids</code> (rule ids from SQL FDD Rules) and/or updating{" "}
          <code>fdd_rules[].bindings.point_ids</code>. Supports <code>import_ready_json</code> wrappers and fenced{" "}
          <code>```json</code> blocks.
        </p>
        <textarea
          className="dm-json-editor"
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder='{"sites":[…],"equipment":[…],"points":[{"id":"…","fdd_rule_ids":["rule-id"]}],"fdd_rules":[…]}'
          spellCheck={false}
        />
        <div className="row">
          <button type="button" disabled={importLoading || !importText.trim()} onClick={() => void doImport()}>
            {importLoading ? "Importing…" : "Import model + FDD assignments"}
          </button>
          <button type="button" className="secondary-btn" disabled={!importText} onClick={() => setImportText("")}>
            Clear import box
          </button>
        </div>
      </section>
    </div>
  );
}
