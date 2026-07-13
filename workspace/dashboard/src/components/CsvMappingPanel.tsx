import { useCallback, useEffect, useRef, useState } from "react";
import { hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  emptyColumnMapDocument,
  exportColumnMapJson,
  fetchColumnMap,
  parseColumnMapJson,
  saveColumnMap,
  SUGGESTED_FDD_ROLES,
  validateColumnMapDocument,
  type ColumnMapDocument,
} from "../lib/columnMap";

type MapRow = { column: string; role: string };

function rowsFromDoc(doc: ColumnMapDocument): MapRow[] {
  const entries = Object.entries(doc.column_map);
  if (!entries.length) return [{ column: "", role: "" }];
  return entries.map(([column, role]) => ({ column, role }));
}

function docFromForm(
  meta: Omit<ColumnMapDocument, "column_map">,
  rows: MapRow[],
): { doc: ColumnMapDocument; incomplete: string[] } {
  const column_map: Record<string, string> = {};
  const incomplete: string[] = [];
  for (const row of rows) {
    const col = row.column.trim();
    const role = row.role.trim();
    if (!col && !role) continue;
    if (col && role) {
      column_map[col] = role;
    } else if (col) {
      incomplete.push(`column '${col}' has no role`);
    } else {
      incomplete.push("role without a column name");
    }
  }
  return { doc: { ...meta, column_map }, incomplete };
}

type Props = {
  /** Prefer session id as dataset_id when present. */
  defaultDatasetId?: string;
  /** CSV headers from latest upload — offered as blank role rows only when user opts in. */
  availableColumns?: string[];
};

export default function CsvMappingPanel({ defaultDatasetId = "", availableColumns = [] }: Props) {
  const [doc, setDoc] = useState<ColumnMapDocument>(() => emptyColumnMapDocument(defaultDatasetId));
  const [rows, setRows] = useState<MapRow[]>([{ column: "", role: "" }]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const applyDoc = useCallback((next: ColumnMapDocument) => {
    setDoc(next);
    setRows(rowsFromDoc(next));
    setValidationErrors([]);
  }, []);

  useEffect(() => {
    if (!defaultDatasetId || doc.dataset_id) return;
    setDoc((prev) => ({ ...prev, dataset_id: defaultDatasetId }));
  }, [defaultDatasetId, doc.dataset_id]);

  async function loadFromServer() {
    if (!hasToken()) {
      setError("Sign in to load mappings.");
      return;
    }
    setBusy("load");
    setError("");
    setStatus("");
    try {
      const id = doc.dataset_id.trim() || defaultDatasetId || undefined;
      const loaded = await fetchColumnMap(id);
      applyDoc(loaded);
      const n = Object.keys(loaded.column_map).length;
      setStatus(
        n
          ? `Loaded mapping for ${loaded.dataset_id || "(no dataset)"} · ${n} column role(s)`
          : `Loaded empty mapping scaffold${loaded.dataset_id ? ` for ${loaded.dataset_id}` : ""} — assign roles explicitly`,
      );
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function saveToServer() {
    if (!hasToken()) {
      setError("Sign in to save mappings.");
      return;
    }
    const { doc: next, incomplete } = docFromForm(
      {
        version: doc.version || 1,
        dataset_id: doc.dataset_id,
        timezone: doc.timezone,
        timestamp_column: doc.timestamp_column,
        equipment: doc.equipment,
      },
      rows,
    );
    const check = validateColumnMapDocument(next);
    const errors = [...incomplete, ...check.errors];
    setValidationErrors(errors);
    if (errors.length) {
      setError("Fix validation errors before saving.");
      return;
    }
    setBusy("save");
    setError("");
    setStatus("");
    try {
      const saved = await saveColumnMap(next);
      applyDoc(saved);
      setStatus(`Saved versioned mapping · ${Object.keys(saved.column_map).length} role(s)`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  function onExport() {
    const { doc: next } = docFromForm(
      {
        version: doc.version || 1,
        dataset_id: doc.dataset_id,
        timezone: doc.timezone,
        timestamp_column: doc.timestamp_column,
        equipment: doc.equipment,
      },
      rows,
    );
    const blob = new Blob([exportColumnMapJson(next)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${next.dataset_id || "column_map"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("Exported mapping JSON");
  }

  function onImportFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = String(reader.result ?? "");
        const parsed = parseColumnMapJson(text);
        applyDoc(parsed);
        const check = validateColumnMapDocument(parsed);
        setValidationErrors(check.errors);
        setError("");
        setStatus(`Imported ${file.name} · roles are as written in the file (not auto-filled)`);
      } catch (e) {
        setError(formatApiError(e));
      }
    };
    reader.readAsText(file);
  }

  function addColumnsFromUpload() {
    const existing = new Set(rows.map((r) => r.column.trim()).filter(Boolean));
    const ts = doc.timestamp_column.trim();
    const toAdd = availableColumns.filter((c) => c && c !== ts && !existing.has(c));
    if (!toAdd.length) {
      setStatus("No new columns from upload to add (roles stay blank until you set them).");
      return;
    }
    setRows((prev) => [
      ...prev.filter((r) => r.column.trim() || r.role.trim()),
      ...toAdd.map((column) => ({ column, role: "" })),
    ]);
    setStatus(`Added ${toAdd.length} column(s) with blank roles — assign roles explicitly`);
  }

  function setMeta<K extends keyof ColumnMapDocument>(key: K, value: ColumnMapDocument[K]) {
    setDoc((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <section className="panel csv-mapping-panel">
      <div className="toolbar toolbar-spaced">
        <h3 className="panel-title" style={{ margin: 0 }}>
          Mapping
        </h3>
        <span className="muted">Versioned column→role JSON · no silent auto-map</span>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {status ? <p className="ok">{status}</p> : null}
      {validationErrors.length > 0 ? (
        <ul className="csv-mapping-errors">
          {validationErrors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}

      <div className="csv-mapping-grid">
        <label>
          Schema version
          <input type="number" min={1} value={doc.version} readOnly className="csv-mapping-input" />
        </label>
        <label>
          Dataset id
          <input
            className="csv-mapping-input"
            value={doc.dataset_id}
            placeholder="e.g. session id or source:csv:…"
            onChange={(e) => setMeta("dataset_id", e.target.value)}
          />
        </label>
        <label>
          Timezone
          <input
            className="csv-mapping-input"
            value={doc.timezone}
            placeholder="America/Chicago"
            list="csv-mapping-tz"
            onChange={(e) => setMeta("timezone", e.target.value)}
          />
          <datalist id="csv-mapping-tz">
            <option value="UTC" />
            <option value="America/Chicago" />
            <option value="America/New_York" />
            <option value="America/Los_Angeles" />
          </datalist>
        </label>
        <label>
          Timestamp column
          <input
            className="csv-mapping-input"
            value={doc.timestamp_column}
            placeholder="timestamp"
            list="csv-mapping-ts-cols"
            onChange={(e) => setMeta("timestamp_column", e.target.value)}
          />
          <datalist id="csv-mapping-ts-cols">
            {availableColumns.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
        <label className="csv-mapping-span">
          Equipment
          <input
            className="csv-mapping-input"
            value={doc.equipment}
            placeholder="equip:ahu-1"
            onChange={(e) => setMeta("equipment", e.target.value)}
          />
        </label>
      </div>

      <div className="csv-mapping-roles-head">
        <strong>Column → role</strong>
        <span className="muted">Add rows manually or from upload headers (roles stay blank)</span>
      </div>
      <table className="csv-mapping-table">
        <thead>
          <tr>
            <th>CSV column</th>
            <th>FDD role</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>
                <input
                  className="csv-mapping-input"
                  value={row.column}
                  list="csv-mapping-cols"
                  placeholder="header"
                  onChange={(e) => {
                    const v = e.target.value;
                    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, column: v } : r)));
                  }}
                />
              </td>
              <td>
                <input
                  className="csv-mapping-input"
                  value={row.role}
                  list="csv-mapping-roles"
                  placeholder="oa_t"
                  onChange={(e) => {
                    const v = e.target.value;
                    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, role: v } : r)));
                  }}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="linkish-btn"
                  onClick={() =>
                    setRows((prev) => {
                      const next = prev.filter((_, j) => j !== i);
                      return next.length ? next : [{ column: "", role: "" }];
                    })
                  }
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <datalist id="csv-mapping-cols">
        {availableColumns.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
      <datalist id="csv-mapping-roles">
        {SUGGESTED_FDD_ROLES.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>

      <div className="toolbar toolbar-spaced csv-mapping-actions">
        <div className="csv-mapping-actions-left">
          <button type="button" className="secondary-btn" onClick={() => setRows((prev) => [...prev, { column: "", role: "" }])}>
            Add row
          </button>
          {availableColumns.length > 0 ? (
            <button type="button" className="secondary-btn" onClick={addColumnsFromUpload}>
              Add columns from upload
            </button>
          ) : null}
        </div>
        <div className="csv-mapping-actions-right">
          <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void loadFromServer()}>
            {busy === "load" ? "Loading…" : "Load"}
          </button>
          <button type="button" className="secondary-btn" onClick={onExport}>
            Export JSON
          </button>
          <label className="secondary-btn csv-mapping-file-btn">
            Import JSON
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onImportFile(f);
                e.target.value = "";
              }}
            />
          </label>
          <button type="button" className="primary-btn" disabled={!!busy} onClick={() => void saveToServer()}>
            {busy === "save" ? "Saving…" : "Save mapping"}
          </button>
        </div>
      </div>
    </section>
  );
}
