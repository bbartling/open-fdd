import { useState } from "react";
import { desktopFetch } from "../lib/api";

type ModelPayload = {
  sites: Array<Record<string, unknown>>;
  equipment: Array<Record<string, unknown>>;
  points: Array<Record<string, unknown>>;
};

export function DataModelPage() {
  const [jsonText, setJsonText] = useState("");
  const [out, setOut] = useState("");
  const [replaceModel, setReplaceModel] = useState(true);

  async function doExport() {
    try {
      const model = await desktopFetch<ModelPayload>("/model/export");
      setJsonText(JSON.stringify(model, null, 2));
      setOut("Exported model JSON.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Export failed: ${message}`);
    }
  }

  async function doImport() {
    try {
      const payload = JSON.parse(jsonText);
      const resp = await desktopFetch<{ sites: number; equipment: number; points: number }>("/model/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload, replace: replaceModel }),
      });
      setOut(`Imported sites=${resp.sites}, equipment=${resp.equipment}, points=${resp.points}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOut(`Import failed: ${message}`);
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data Model BRICK</h2>
      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <button onClick={() => void doExport()}>Export JSON</button>
        <button onClick={() => void doImport()}>Import JSON</button>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            style={{ width: "auto" }}
            type="checkbox"
            checked={replaceModel}
            onChange={(e) => setReplaceModel(e.target.checked)}
          />
          Replace existing model
        </label>
      </div>
      <textarea
        value={jsonText}
        onChange={(e) => setJsonText(e.target.value)}
        placeholder="Paste AI-tagged model JSON here"
        style={{ minHeight: 260 }}
      />
      <textarea readOnly value={out} style={{ marginTop: 10, minHeight: 64 }} />
    </div>
  );
}
