import { useCallback, useEffect, useState } from "react";
import PythonCodeEditor from "../components/PythonCodeEditor";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

const DEFAULT_RULE = `def evaluate(row, cfg, prev_row=None, rows=None):
    """Flag when supply air temp exceeds cfg['high']. Use row keys from Data Model fdd_input."""
    high = float(cfg.get("high", 75.0))
    sat = row.get("SAT") or row.get("Supply_Air_Temperature_Sensor") or row.get("temp")
    if sat is None:
        return False
    return float(sat) > high
`;

type Mode = "rule" | "script";

type SavedRule = {
  id: string;
  name: string;
  mode: Mode;
  severity: string;
  enabled: boolean;
  source_path?: string;
  fault_code?: string;
};

export default function RuleLabPage() {
  const [mode, setMode] = useState<Mode>("rule");
  const [code, setCode] = useState(DEFAULT_RULE);
  const [sourcePath, setSourcePath] = useState("");
  const [cfgHigh, setCfgHigh] = useState("75");
  const [console, setConsole] = useState("");
  const [busy, setBusy] = useState(false);
  const [ruleName, setRuleName] = useState("Supply air temp high");
  const [severity, setSeverity] = useState("warning");
  const [faultCode, setFaultCode] = useState("");
  const [faultCodes, setFaultCodes] = useState<{ code: string; title: string; family: string }[]>([]);
  const [saved, setSaved] = useState<SavedRule[]>([]);
  const [activeRuleId, setActiveRuleId] = useState<string>("");

  const refreshSaved = useCallback(async () => {
    const res = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
    setSaved(res.rules || []);
    return res.rules || [];
  }, []);

  const loadRuleSource = useCallback(async (ruleId: string) => {
    const res = await apiFetch<{ code: string; path: string }>(`/api/rules/saved/${ruleId}/source`);
    setCode(res.code || DEFAULT_RULE);
    setSourcePath(res.path || "");
  }, []);

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
  }, [refreshSaved]);

  useEffect(() => {
    if (activeRuleId) void loadRuleSource(activeRuleId).catch((e) => setConsole(formatApiError(e)));
  }, [activeRuleId, loadRuleSource]);

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
      setConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function testRun() {
    setBusy(true);
    try {
      const high = Number(cfgHigh);
      if (mode === "rule" && !Number.isFinite(high)) {
        setConsole("cfg high must be a finite number");
        return;
      }
      if (mode === "rule") {
        const res = await apiFetch<{
          rows: number;
          flagged: number;
          data_source?: string;
          site_id?: string;
          preview_columns?: string[];
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
          `site=${res.site_id} source=${res.data_source} rows=${res.rows} flagged=${res.flagged}`,
          `columns: ${(res.preview_columns || []).join(", ")}`,
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
          data_source?: string;
          site_id?: string;
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
              `site=${res.site_id} source=${res.data_source}`,
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
      setConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveSource() {
    setBusy(true);
    try {
      if (activeRuleId) {
        const res = await apiFetch<{ path: string }>(`/api/rules/saved/${activeRuleId}/source`, {
          method: "PUT",
          body: JSON.stringify({ code }),
        });
        setSourcePath(res.path);
        setConsole(`Saved ${res.path} — AI agents and operators share this file.`);
        await refreshSaved();
        return;
      }
      const res = await apiFetch<{ rule: SavedRule }>("/api/rules/save", {
        method: "POST",
        body: JSON.stringify({
          name: ruleName,
          mode,
          code,
          config: mode === "rule" ? { high: Number(cfgHigh) || 75 } : {},
          severity,
          fault_code: faultCode.trim(),
          bindings: { point_ids: [], equipment_ids: [], brick_types: [] },
        }),
      });
      setActiveRuleId(res.rule.id);
      setSourcePath(res.rule.source_path || "");
      setConsole(`Created rule "${res.rule.name}" → map it on the Data Model tab.`);
      await refreshSaved();
    } catch (e) {
      setConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function selectRule(rule: SavedRule) {
    setActiveRuleId(rule.id);
    setRuleName(rule.name);
    setMode(rule.mode);
    setSeverity(rule.severity);
    setFaultCode(rule.fault_code || "");
    setSourcePath(rule.source_path || "");
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Rule Lab"
        subtitle={
          <>
            Edit the on-disk <code>.py</code> rule file below. Test runs against feather / live site data. Map rules
            to BRICK points on the <a href="/data-model">Data Model</a> tab.
          </>
        }
      />

      <div className="panel rule-lab-toolbar">
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="rule-select">
              Rule
            </label>
            <select
              id="rule-select"
              value={activeRuleId}
              onChange={(e) => {
                const id = e.target.value;
                if (!id) {
                  setActiveRuleId("");
                  setCode(DEFAULT_RULE);
                  setSourcePath("");
                  return;
                }
                const rule = saved.find((r) => r.id === id);
                if (rule) selectRule(rule);
              }}
            >
              <option value="">New rule…</option>
              {saved.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
          {!activeRuleId ? (
            <>
              <div className="field">
                <label className="field-label" htmlFor="rule-name">
                  Name
                </label>
                <input id="rule-name" value={ruleName} onChange={(e) => setRuleName(e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="rule-fault-code">
                  Fault code
                </label>
                <input
                  id="rule-fault-code"
                  list="fault-code-list"
                  value={faultCode}
                  onChange={(e) => setFaultCode(e.target.value)}
                />
              </div>
            </>
          ) : null}
          <div className="field">
            <label className="field-label" htmlFor="rule-mode">
              Mode
            </label>
            <select
              id="rule-mode"
              value={mode}
              disabled={!!activeRuleId}
              onChange={(e) => {
                const m = e.target.value as Mode;
                setMode(m);
                if (!activeRuleId) setCode(m === "rule" ? DEFAULT_RULE : "# df script\nout = {'df': df}");
              }}
            >
              <option value="rule">Per-row evaluate()</option>
              <option value="script">DataFrame script</option>
            </select>
          </div>
          {mode === "rule" ? (
            <div className="field">
              <label className="field-label" htmlFor="rule-cfg-high">
                cfg high
              </label>
              <input id="rule-cfg-high" value={cfgHigh} onChange={(e) => setCfgHigh(e.target.value)} />
            </div>
          ) : null}
        </div>
        <div className="toolbar">
          <button type="button" className="secondary" disabled={busy} onClick={() => void lint()}>
            Lint
          </button>
          <button type="button" disabled={busy} onClick={() => void testRun()}>
            Test
          </button>
          <button type="button" disabled={busy} onClick={() => void saveSource()}>
            Save .py
          </button>
        </div>
      </div>

      {sourcePath ? (
        <p className="muted code-path">
          File: <code>{sourcePath}</code>
        </p>
      ) : null}

      <datalist id="fault-code-list">
        {faultCodes.map((c) => (
          <option key={c.code} value={c.code}>
            {c.family} · {c.title}
          </option>
        ))}
      </datalist>

      <div className="panel">
        <PythonCodeEditor value={code} onChange={setCode} height="420px" />
      </div>
      <div className="panel">
        <h3 className="panel-title">Console</h3>
        <div className="console">{console || "Lint or Test to run against live feather data."}</div>
      </div>
    </div>
  );
}
