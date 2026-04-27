import { useState } from "react";
import { desktopFetch } from "../lib/api";

type RuleResponse = {
  input_rows: number;
  output_rows: number;
  columns: string[];
  fault_totals: Record<string, number>;
  preview: string;
};

export function FaultsPage() {
  const [siteId, setSiteId] = useState("");
  const [source, setSource] = useState("csv");
  const [rulesPath, setRulesPath] = useState("");
  const [chunkRows, setChunkRows] = useState("0");
  const [output, setOutput] = useState("");

  async function runRules() {
    const out = await desktopFetch<RuleResponse>("/rules/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        site_id: siteId,
        source,
        rules_path: rulesPath,
        chunk_rows: Number(chunkRows || "0"),
      }),
    });
    setOutput(
      `Input rows: ${out.input_rows}\nOutput rows: ${out.output_rows}\n` +
        `Columns: ${out.columns.join(", ")}\nFault totals: ${JSON.stringify(out.fault_totals, null, 2)}\n\nPreview:\n${out.preview}`,
    );
  }

  return (
    <div className="card">
      <h2 className="title">Faults</h2>
      <div className="grid-two">
        <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site id" />
        <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="source" />
        <input value={rulesPath} onChange={(e) => setRulesPath(e.target.value)} placeholder="rules path directory" />
        <input value={chunkRows} onChange={(e) => setChunkRows(e.target.value)} placeholder="chunk rows" />
      </div>
      <div style={{ marginTop: 12 }}>
        <button onClick={() => void runRules()}>Run Rules</button>
      </div>
      <textarea readOnly value={output} style={{ marginTop: 12, minHeight: 260 }} />
    </div>
  );
}
