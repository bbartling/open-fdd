import { useState } from "react";
import PythonCodeEditor from "../components/PythonCodeEditor";
import { apiFetch } from "../lib/api";

const DEFAULT_RULE = `def evaluate(row, cfg, prev_row=None, rows=None):
    """Flag when supply air temp exceeds cfg['high']."""
    high = float(cfg.get("high", 75.0))
    sat = row.get("SAT") or row.get("temp")
    if sat is None:
        return False
    return float(sat) > high
`;

const DEFAULT_SCRIPT = `# Full DataFrame mode: mutate df, set out dict
import pandas as pd
from open_fdd.engine import RuleRunner

df = df.copy()
df["scratch_flag"] = (df["SAT"] > 75).astype(int)
out = {"df": df, "events": [{"type": "note", "text": "scratch_flag added"}]}
`;

type Mode = "rule" | "script";

export default function RuleLabPage() {
  const [mode, setMode] = useState<Mode>("rule");
  const [code, setCode] = useState(DEFAULT_RULE);
  const [cfgHigh, setCfgHigh] = useState("75");
  const [console, setConsole] = useState("");
  const [busy, setBusy] = useState(false);

  async function lint() {
    setBusy(true);
    try {
      const res = await apiFetch<{ ok: boolean; issues: { message: string; severity: string }[] }>(
        "/api/playground/lint",
        { method: "POST", body: JSON.stringify({ code }) },
      );
      setConsole(
        res.issues.length
          ? res.issues.map((i) => `${i.severity}: ${i.message}`).join("\n")
          : res.ok
            ? "Lint OK"
            : "Lint failed",
      );
    } catch (e) {
      setConsole(String(e));
    } finally {
      setBusy(false);
    }
  }

  function parseCfgHigh(): number | null {
    const high = Number(cfgHigh);
    if (!Number.isFinite(high)) {
      return null;
    }
    return high;
  }

  async function testRun() {
    setBusy(true);
    try {
      if (mode === "rule") {
        const high = parseCfgHigh();
        if (high === null) {
          setConsole("cfg high must be a finite number");
          return;
        }
        const res = await apiFetch<{
          ok: boolean;
          rows: number;
          flagged: number;
          events: { type: string; text?: string; status?: string; row?: number }[];
        }>("/api/playground/test-rule", {
          method: "POST",
          body: JSON.stringify({
            code,
            config: { high },
            limit: 200,
          }),
        });
        const lines = [
          `rows=${res.rows} flagged=${res.flagged}`,
          ...res.events.map((ev) => {
            if (ev.type === "stdout") return ev.text || "";
            if (ev.type === "summary") return JSON.stringify(ev);
            return `[${ev.type}] row=${ev.row} status=${ev.status}`;
          }),
        ];
        setConsole(lines.filter(Boolean).join("\n"));
      } else {
        const res = await apiFetch<{
          ok: boolean;
          stdout?: string;
          error?: string;
          flag_columns?: string[];
          preview?: Record<string, unknown>[];
        }>("/api/playground/run-script", {
          method: "POST",
          body: JSON.stringify({ code, limit: 500 }),
        });
        if (!res.ok) {
          setConsole(res.error || "script failed");
        } else {
          setConsole(
            [
              res.stdout,
              `flag_columns: ${(res.flag_columns || []).join(", ")}`,
              `preview rows: ${res.preview?.length ?? 0}`,
            ]
              .filter(Boolean)
              .join("\n"),
          );
        }
      }
    } catch (e) {
      setConsole(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>Rule Lab (Bake-a-Py)</h2>
      <p className="muted">
        Per-row <code>evaluate()</code> or full <code>df</code> scripts with open_fdd.engine on the
        server.
      </p>
      <div className="row panel">
        <label>
          Mode{" "}
          <select
            value={mode}
            onChange={(e) => {
              const m = e.target.value as Mode;
              setMode(m);
              setCode(m === "rule" ? DEFAULT_RULE : DEFAULT_SCRIPT);
            }}
          >
            <option value="rule">Per-row rule</option>
            <option value="script">DataFrame script</option>
          </select>
        </label>
        {mode === "rule" ? (
          <label>
            cfg high (°F){" "}
            <input value={cfgHigh} onChange={(e) => setCfgHigh(e.target.value)} style={{ width: 80 }} />
          </label>
        ) : null}
        <button type="button" className="secondary" disabled={busy} onClick={lint}>
          Lint
        </button>
        <button type="button" disabled={busy} onClick={testRun}>
          Test on server
        </button>
      </div>
      <div className="panel">
        <PythonCodeEditor value={code} onChange={setCode} height="360px" />
      </div>
      <div className="panel">
        <h3>Console</h3>
        <div className="console">{console || "Run Test to execute on bridge host."}</div>
      </div>
    </div>
  );
}
