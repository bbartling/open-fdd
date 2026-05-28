import { useState } from "react";
import { apiFetch } from "../lib/api";

export default function FddPage() {
  const [console, setConsole] = useState("");
  const [busy, setBusy] = useState(false);

  async function runYamlRules() {
    setBusy(true);
    try {
      const res = await apiFetch<{
        ok: boolean;
        flag_columns: string[];
        flag_totals: Record<string, number>;
        rows: number;
      }>("/api/rules/run", {
        method: "POST",
        body: JSON.stringify({ column_map: { SAT: "SAT" } }),
      });
      setConsole(
        `rows=${res.rows}\nflags=${res.flag_columns.join(", ")}\ntotals=${JSON.stringify(res.flag_totals, null, 2)}`,
      );
    } catch (e) {
      setConsole(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>YAML FDD (RuleRunner)</h2>
      <p className="muted">
        Runs rules in <code>workspace/data/rules/</code> via open_fdd.engine on the demo frame.
        Flag columns are integer 0/1.
      </p>
      <div className="row">
        <button type="button" disabled={busy} onClick={runYamlRules}>
          Run RuleRunner
        </button>
      </div>
      <div className="panel console">{console || "Click Run RuleRunner."}</div>
    </div>
  );
}
