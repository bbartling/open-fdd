import { useEffect, useState } from "react";
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

type SavedRule = {
  id: string;
  name: string;
  mode: Mode;
  severity: string;
  enabled: boolean;
  applies_to?: { equipment_type?: string; brick_type?: string; site_ids?: string[] };
};

export default function RuleLabPage() {
  const [mode, setMode] = useState<Mode>("rule");
  const [code, setCode] = useState(DEFAULT_RULE);
  const [cfgHigh, setCfgHigh] = useState("75");
  const [console, setConsole] = useState("");
  const [busy, setBusy] = useState(false);
  const [ruleName, setRuleName] = useState("Supply air temp high");
  const [equipmentType, setEquipmentType] = useState("");
  const [brickType, setBrickType] = useState("");
  const [severity, setSeverity] = useState("warning");
  const [faultCode, setFaultCode] = useState("");
  const [faultCodes, setFaultCodes] = useState<{ code: string; title: string; family: string }[]>([]);
  const [saved, setSaved] = useState<SavedRule[]>([]);

  async function refreshSaved() {
    try {
      const res = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
      setSaved(res.rules || []);
    } catch (e) {
      setConsole(String(e));
    }
  }

  useEffect(() => {
    void refreshSaved();
    apiFetch<{ families: { family: string; codes: { code: string; title: string }[] }[] }>(
      "/api/faults/catalog",
    )
      .then((res) =>
        setFaultCodes(
          (res.families || []).flatMap((f) =>
            f.codes.map((c) => ({ code: c.code, title: c.title, family: f.family })),
          ),
        ),
      )
      .catch(() => undefined);
  }, []);

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

  async function saveRule() {
    setBusy(true);
    try {
      const high = parseCfgHigh();
      const res = await apiFetch<{ ok: boolean; rule: SavedRule }>("/api/rules/save", {
        method: "POST",
        body: JSON.stringify({
          name: ruleName,
          mode,
          code,
          config: mode === "rule" && high !== null ? { high } : {},
          severity,
          fault_code: faultCode.trim(),
          applies_to: {
            equipment_type: equipmentType.trim(),
            brick_type: brickType.trim(),
            site_ids: [],
          },
        }),
      });
      setConsole(`Saved rule "${res.rule.name}" (${res.rule.id}).`);
      await refreshSaved();
    } catch (e) {
      setConsole(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function deleteRule(id: string) {
    setBusy(true);
    try {
      await apiFetch(`/api/rules/saved/${id}`, { method: "DELETE" });
      await refreshSaved();
    } catch (e) {
      setConsole(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runBatch() {
    setBusy(true);
    try {
      const res = await apiFetch<{
        rules_run: number;
        site_runs: number;
        flagged_runs: number;
        error_runs: number;
      }>("/api/rules/batch", { method: "POST", body: JSON.stringify({ limit: 1000 }) });
      setConsole(
        `Batch run across BRICK model: rules=${res.rules_run} site_runs=${res.site_runs} ` +
          `flagged=${res.flagged_runs} errors=${res.error_runs}. ` +
          `Faults now drive the building check-engine light.`,
      );
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
        Per-row <code>evaluate()</code> or full <code>df</code> Python scripts. Rules bind to BRICK{" "}
        <code>fdd_input</code> / <code>external_id</code> from{" "}
        <a href="/data-model">Data Model</a> — no YAML.
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

      <div className="panel">
        <h3>Save &amp; apply across the BRICK model</h3>
        <p className="muted">
          Test above, then save. Saved rules are applied to every matching site by the scheduled FDD
          runner and turn the <a href="/">building check-engine light</a> yellow/red on faults.
        </p>
        <div className="row">
          <label>
            Name{" "}
            <input value={ruleName} onChange={(e) => setRuleName(e.target.value)} style={{ width: 220 }} />
          </label>
          <label>
            Severity{" "}
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </label>
          <label>
            Fault code{" "}
            <input
              list="fault-code-list"
              value={faultCode}
              onChange={(e) => setFaultCode(e.target.value)}
              placeholder="e.g. AHU-02 (from catalog)"
              style={{ width: 200 }}
            />
            <datalist id="fault-code-list">
              {faultCodes.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.family} · {c.title}
                </option>
              ))}
            </datalist>
          </label>
        </div>
        <div className="row">
          <label>
            Applies to equipment_type{" "}
            <input
              value={equipmentType}
              onChange={(e) => setEquipmentType(e.target.value)}
              placeholder="e.g. Air_Handling_Unit (blank = all)"
              style={{ width: 240 }}
            />
          </label>
          <label>
            or brick_type{" "}
            <input
              value={brickType}
              onChange={(e) => setBrickType(e.target.value)}
              placeholder="e.g. Supply_Air_Temperature_Sensor"
              style={{ width: 240 }}
            />
          </label>
        </div>
        <div className="row">
          <button type="button" disabled={busy} onClick={saveRule}>
            Save rule
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={runBatch}>
            Run batch now
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Saved rules ({saved.length})</h3>
        {saved.length ? (
          <ul className="check-engine-list">
            {saved.map((r) => (
              <li key={r.id}>
                <strong>{r.name}</strong>
                <span className="badge">{r.mode}</span>
                <span className="badge">{r.severity}</span>
                {r.applies_to?.equipment_type ? (
                  <span className="muted"> · {r.applies_to.equipment_type}</span>
                ) : null}
                {r.applies_to?.brick_type ? (
                  <span className="muted"> · {r.applies_to.brick_type}</span>
                ) : null}
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => deleteRule(r.id)}
                  style={{ marginLeft: 8 }}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No saved rules yet. Test a rule above, then Save.</p>
        )}
      </div>
    </div>
  );
}
