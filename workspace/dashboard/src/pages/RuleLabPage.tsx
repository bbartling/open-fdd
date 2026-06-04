import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PythonCodeEditor from "../components/PythonCodeEditor";
import PageHeader from "../components/PageHeader";
import RuleConfigPanel, { configFromRecord, configToRecord } from "../components/RuleConfigPanel";
import RuleLabConsole, { consoleTextToLines } from "../components/RuleLabConsole";
import FaultCodeSelect from "../components/FaultCodeSelect";
import { useTheme } from "../contexts/theme-context";
import { apiFetch, fetchAuthMe } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { displayRuleName, formatRuleLabel } from "../lib/ruleDisplay";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import {
  formatBatchSummary,
  formatLintIssues,
  formatRuleTestEvents,
  type LintIssue,
} from "../lib/rule-lab-console";

const DEFAULT_RULE = `def evaluate(row, cfg, prev_row=None, rows=None):
    """Flag when supply air temp exceeds cfg['high']. Use row keys from Data Model fdd_input."""
    high = float(cfg.get("high", 75.0))
    sat = row.get("SAT") or row.get("Supply_Air_Temperature_Sensor") or row.get("temp")
    if sat is None:
        return False
    return float(sat) > high
`;

const DEFAULT_SCRIPT = `# df script — set out = {"df": df, "events": [...]}
df = df.copy()
df["custom_flag"] = 0
out = {"df": df, "events": [{"type": "note", "text": "edit me"}]}
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
  config?: Record<string, unknown>;
  bindings?: {
    point_ids?: string[];
    equipment_ids?: string[];
    brick_types?: string[];
  };
};

function syntaxPillClass(ok: boolean | null, busy: boolean): string {
  if (busy) return "syntax-pill pending";
  if (ok === true) return "syntax-pill ok";
  if (ok === false) return "syntax-pill err";
  return "syntax-pill";
}

export default function RuleLabPage() {
  const { theme, toggleTheme } = useTheme();
  const activeSiteId = useActiveSiteId();
  const [mode, setMode] = useState<Mode>("rule");
  const [code, setCode] = useState(DEFAULT_RULE);
  const [sourcePath, setSourcePath] = useState("");
  const [cfg, setCfg] = useState<Record<string, string>>({ high: "75" });
  const [consoleText, setConsoleText] = useState("");
  const [busy, setBusy] = useState(false);
  const [lintBusy, setLintBusy] = useState(false);
  const [syntaxOk, setSyntaxOk] = useState<boolean | null>(null);
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [ruleName, setRuleName] = useState("Supply air temp high");
  const [severity, setSeverity] = useState("warning");
  const [saved, setSaved] = useState<SavedRule[]>([]);
  const [activeRuleId, setActiveRuleId] = useState<string>("");
  const [authRole, setAuthRole] = useState<string | null>(null);
  const [faultCode, setFaultCode] = useState("");
  const [dirty, setDirty] = useState(false);
  const lintTimer = useRef<number | null>(null);

  useEffect(() => {
    fetchAuthMe()
      .then((me) => setAuthRole(me.role))
      .catch(() => setAuthRole(null));
  }, []);

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
  }, [refreshSaved]);

  useEffect(() => {
    if (activeRuleId) void loadRuleSource(activeRuleId).catch((e) => setConsoleText(formatApiError(e)));
  }, [activeRuleId, loadRuleSource]);

  const runDebouncedLint = useCallback(
    (source: string, lintMode: Mode) => {
      if (lintTimer.current) window.clearTimeout(lintTimer.current);
      lintTimer.current = window.setTimeout(() => {
        setLintBusy(true);
        apiFetch<{ ok: boolean; issues: LintIssue[] }>("/api/playground/lint", {
          method: "POST",
          body: JSON.stringify({ code: source, mode: lintMode }),
        })
          .then((res) => {
            setSyntaxOk(res.ok);
            setLintIssues(res.issues || []);
          })
          .catch(() => {
            setSyntaxOk(null);
            setLintIssues([]);
          })
          .finally(() => setLintBusy(false));
      }, 400);
    },
    [],
  );

  useEffect(() => {
    runDebouncedLint(code, mode);
    return () => {
      if (lintTimer.current) window.clearTimeout(lintTimer.current);
    };
  }, [code, mode, runDebouncedLint]);

  function markDirty() {
    setDirty(true);
  }

  function onCodeChange(next: string) {
    setCode(next);
    markDirty();
  }

  function onCfgChange(next: Record<string, string>) {
    setCfg(next);
    markDirty();
  }

  function appendConsole(text: string) {
    setConsoleText((prev) => (prev ? `${prev}\n${text}` : text));
  }

  function preservedBindings(existing?: SavedRule["bindings"]): SavedRule["bindings"] {
    return {
      point_ids: [...(existing?.point_ids ?? [])],
      equipment_ids: [...(existing?.equipment_ids ?? [])],
      brick_types: [...(existing?.brick_types ?? [])],
    };
  }

  async function lintNow() {
    setBusy(true);
    try {
      const res = await apiFetch<{ ok: boolean; issues: LintIssue[] }>("/api/playground/lint", {
        method: "POST",
        body: JSON.stringify({ code, mode }),
      });
      setSyntaxOk(res.ok);
      setLintIssues(res.issues || []);
      appendConsole(formatLintIssues(res.issues || []));
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function testRun() {
    if (syntaxOk === false) {
      appendConsole("Fix syntax errors before test (see pill above editor).");
      return;
    }
    const rule = saved.find((r) => r.id === activeRuleId);
    const pointId = rule?.bindings?.point_ids?.[0];
    if (mode === "rule" && !pointId) {
      appendConsole(
        "Quick test needs one bound point — use FDD assignments → Test rule against one sensor, or add point_ids to this rule's bindings.",
      );
      return;
    }
    setBusy(true);
    setConsoleText("");
    try {
      if (mode === "rule") {
        const res = await apiFetch<{
          rows: number;
          flagged: number;
          data_source?: string;
          value_column?: string;
          events: { type: string; text?: string }[];
          trace?: string;
          error?: string;
          ms?: number;
        }>("/api/playground/test-rule", {
          method: "POST",
          body: JSON.stringify({
            code,
            config: configFromRecord(cfg),
            site_id: activeSiteId || undefined,
            point_keys: [pointId],
            lookback_hours: 24,
            limit: 120,
            chunk_hours: 0,
          }),
        });
        setConsoleText(
          [
            `>>> Quick test (first bound point) rows=${res.rows} flagged=${res.flagged} · ${res.data_source}`,
            res.value_column ? `column: ${res.value_column}` : "",
            formatRuleTestEvents(res.events || [], { maxLines: 28 }),
            res.trace || res.error || "",
          ]
            .filter(Boolean)
            .join("\n\n"),
        );
      } else {
        const res = await apiFetch<{
          ok: boolean;
          stdout?: string;
          error?: string;
          trace?: string;
        }>("/api/playground/run-script", {
          method: "POST",
          body: JSON.stringify({ code, limit: 500 }),
        });
        setConsoleText(
          res.ok
            ? [res.stdout, res.trace].filter(Boolean).join("\n\n")
            : [res.error, res.trace].filter(Boolean).join("\n\n"),
        );
      }
    } catch (e) {
      setConsoleText(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveRule(options?: { suppressBusy?: boolean }) {
    const suppressBusy = options?.suppressBusy === true;
    if (syntaxOk === false) {
      appendConsole("Cannot save — fix syntax errors first.");
      return;
    }
    if (!suppressBusy) setBusy(true);
    try {
      let bindingsSource: SavedRule["bindings"] | undefined;
      if (activeRuleId) {
        try {
          const fresh = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
          bindingsSource = fresh.rules?.find((r) => r.id === activeRuleId)?.bindings;
        } catch {
          bindingsSource = saved.find((r) => r.id === activeRuleId)?.bindings;
        }
      }
      const payload = {
        id: activeRuleId || undefined,
        name: ruleName,
        mode,
        code,
        config: configFromRecord(cfg),
        severity,
        fault_code: faultCode,
        bindings: preservedBindings(bindingsSource),
      };
      if (activeRuleId) {
        const putRes = await apiFetch<{ path: string }>(`/api/rules/saved/${activeRuleId}/source`, {
          method: "PUT",
          body: JSON.stringify({ code }),
        });
        const saveRes = await apiFetch<{ rule: SavedRule }>("/api/rules/save", {
          method: "POST",
          body: JSON.stringify({ ...payload, id: activeRuleId }),
        });
        setSourcePath(putRes.path || saveRes.rule.source_path || sourcePath);
        appendConsole(`>>> Updated rule .py — ${putRes.path || sourcePath}`);
      } else {
        const res = await apiFetch<{ rule: SavedRule }>("/api/rules/save", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setActiveRuleId(res.rule.id);
        setSourcePath(res.rule.source_path || "");
        appendConsole(`>>> Created rule "${formatRuleLabel(res.rule.name)}". Assign points on FDD assignments.`);
      }
      setDirty(false);
      await refreshSaved();
    } catch (e) {
      appendConsole(formatApiError(e));
      if (suppressBusy) throw e;
    } finally {
      if (!suppressBusy) setBusy(false);
    }
  }

  async function updateAllRecords() {
    setBusy(true);
    try {
      if (dirty && activeRuleId) await saveRule({ suppressBusy: true });
      const res = await apiFetch<{
        rules_run?: number;
        flagged_runs?: number;
        runs?: { rule_name?: string; site_id?: string; flagged?: number; status?: string }[];
      }>("/api/rules/batch", {
        method: "POST",
        body: JSON.stringify({ limit: 50000, chunk_hours: 0, lookback_hours: 1, use_chunks: false }),
      });
      setConsoleText(formatBatchSummary(res));
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function selectRule(rule: SavedRule) {
    setActiveRuleId(rule.id);
    setRuleName(displayRuleName(rule.name));
    setMode(rule.mode);
    setSeverity(rule.severity);
    setFaultCode(rule.fault_code || "");
    setSourcePath(rule.source_path || "");
    setCfg(configToRecord(rule.config || {}));
    setDirty(false);
  }

  function addRule() {
    setActiveRuleId("");
    setRuleName("New rule");
    setMode("rule");
    setCode(DEFAULT_RULE);
    setCfg({ high: "75" });
    setSourcePath("");
    setFaultCode("");
    setDirty(true);
  }

  async function removeRule() {
    if (!activeRuleId) return;
    if (!window.confirm(`Delete rule "${ruleName}"?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/rules/saved/${activeRuleId}`, { method: "DELETE" });
      const list = await refreshSaved();
      if (list[0]) selectRule(list[0]);
      else addRule();
      appendConsole(`>>> Deleted rule ${activeRuleId}`);
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  const syntaxTitle = useMemo(() => {
    if (lintBusy) return "Checking syntax…";
    if (syntaxOk === true) return "Syntax OK";
    if (syntaxOk === false) return lintIssues.find((i) => i.severity === "error")?.message || "Syntax error";
    return "Syntax not checked";
  }, [lintBusy, syntaxOk, lintIssues]);

  const consoleLines = useMemo(() => consoleTextToLines(consoleText), [consoleText]);

  return (
    <div className="page page-wide rule-lab-page">
      <PageHeader
        title="Rule Lab"
        subtitle={
          <>
            Author and lint <code>.py</code> rules. Map points and run full sensor tests on{" "}
            <a href="/fdd-assignments">FDD assignments</a>.
          </>
        }
      />

      {authRole === "operator" ? (
        <p className="error panel">
          Signed in as <strong>operator</strong>. Rule Lab requires <strong>integrator</strong> or{" "}
          <strong>agent</strong>.
        </p>
      ) : null}

      <div className="panel rule-lab-toolbar">
        <div className="rule-lab-rule-row">
          <label className="field-label" htmlFor="rule-select">
            Rule
          </label>
          <div className="rule-switcher">
            <button
              type="button"
              className="secondary icon-btn"
              disabled={!activeRuleId || busy}
              onClick={() => void removeRule()}
              title="Remove rule"
            >
              −
            </button>
            <select
              id="rule-select"
              value={activeRuleId}
              onChange={(e) => {
                const id = e.target.value;
                if (!id) {
                  addRule();
                  return;
                }
                const r = saved.find((x) => x.id === id);
                if (r) selectRule(r);
              }}
            >
              {!activeRuleId ? <option value="">New rule (unsaved)</option> : null}
              {saved.map((r) => (
                <option key={r.id} value={r.id}>
                  {formatRuleLabel(r.name)}
                </option>
              ))}
            </select>
            <button type="button" className="secondary icon-btn" disabled={busy} onClick={addRule} title="Add rule">
              +
            </button>
          </div>
          <span className={syntaxPillClass(syntaxOk, lintBusy)} title={syntaxTitle}>
            {lintBusy ? "…" : syntaxOk === true ? "syntax ok" : syntaxOk === false ? "syntax err" : "syntax —"}
          </span>
        </div>

        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="rule-name">
              Name
            </label>
            <input
              id="rule-name"
              value={ruleName}
              onChange={(e) => {
                setRuleName(e.target.value);
                markDirty();
              }}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="rule-mode">
              Mode
            </label>
            <select
              id="rule-mode"
              value={mode}
              onChange={(e) => {
                const m = e.target.value as Mode;
                setMode(m);
                if (!activeRuleId) setCode(m === "rule" ? DEFAULT_RULE : DEFAULT_SCRIPT);
                markDirty();
              }}
            >
              <option value="rule">Per-row evaluate()</option>
              <option value="script">DataFrame script</option>
            </select>
          </div>
          <div className="field form-grid-span">
            <FaultCodeSelect
              value={faultCode}
              disabled={busy || authRole === "operator"}
              onChange={(c) => {
                setFaultCode(c);
                markDirty();
              }}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="rule-severity">
              Severity
            </label>
            <select id="rule-severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </div>
        </div>

        {mode === "rule" ? <RuleConfigPanel config={cfg} onChange={onCfgChange} /> : null}

        <div className="toolbar rule-lab-actions">
          <button type="button" className="secondary" disabled={busy} onClick={() => void lintNow()}>
            Lint
          </button>
          <button type="button" disabled={busy || syntaxOk === false} onClick={() => void testRun()}>
            Quick test
          </button>
          <button type="button" disabled={busy || authRole === "operator"} onClick={() => void saveRule()}>
            {activeRuleId ? "Update rule .py" : "Save rule .py"}
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || authRole === "operator"}
            onClick={() => void updateAllRecords()}
          >
            Update all records
          </button>
          <button type="button" className="secondary" onClick={toggleTheme} title="Toggle editor theme">
            {theme === "dark" ? "Light editor" : "Dark editor"}
          </button>
          {dirty ? <span className="muted dirty-hint">Unsaved changes</span> : null}
        </div>
      </div>

      {sourcePath ? (
        <p className="muted code-path">
          File: <code>{sourcePath}</code>
        </p>
      ) : null}

      <div className="panel rule-lab-editor-panel">
        <PythonCodeEditor value={code} onChange={onCodeChange} height="480px" lintIssues={lintIssues} />
      </div>

      <RuleLabConsole
        lines={consoleLines}
        placeholder="Lint, quick test, or batch output."
        footer={
          <button type="button" className="secondary small-btn" onClick={() => setConsoleText("")}>
            Clear
          </button>
        }
      />
    </div>
  );
}
