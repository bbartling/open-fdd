import { useState } from "react";
import { desktopFetch, desktopFetchText } from "../lib/api";
import { writeTtlToPopup } from "../lib/ttl-popup";

type ModelPayload = {
  sites: Array<Record<string, unknown>>;
  equipment: Array<Record<string, unknown>>;
  points: Array<Record<string, unknown>>;
};

export function DataModelPage() {
  const [jsonText, setJsonText] = useState("");
  const [out, setOut] = useState("");
  const [replaceModel, setReplaceModel] = useState(true);
  const [ttlLoading, setTtlLoading] = useState(false);

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

  async function doViewTtl() {
    setTtlLoading(true);
    const ttlPath = "/data-model/ttl?save=false";
    const popup = window.open("", "_blank");
    if (!popup) {
      setOut("Popup blocked. Allow popups and try again.");
      setTtlLoading(false);
      return;
    }
    popup.document.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head><body style="font-family:ui-sans-serif,system-ui,sans-serif;padding:1rem;background:#ffffff;color:#111111;"><p style="margin:0 0 .75rem 0;">Loading TTL graph...</p></body></html>`,
    );
    popup.document.close();
    try {
      const ttl = await desktopFetchText(ttlPath, { headers: { Accept: "text/plain" } });
      writeTtlToPopup(popup, ttl);
    } catch (error) {
      try {
        popup.location.href = ttlPath;
      } catch {
        popup.close?.();
      }
      const message = error instanceof Error ? error.message : String(error);
      setOut(`TTL view failed: ${message}`);
    } finally {
      setTtlLoading(false);
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data Model BRICK</h2>
      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <button onClick={() => void doExport()}>Export JSON</button>
        <button onClick={() => void doImport()}>Import JSON</button>
        <button onClick={() => void doViewTtl()}>{ttlLoading ? "Loading TTL..." : "View full data model (TTL)"}</button>
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
