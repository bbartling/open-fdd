import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PythonCodeEditor from "../components/PythonCodeEditor";
import PageHeader from "../components/PageHeader";
import RuleConfigPanel, { configFromRecord, configToRecord } from "../components/RuleConfigPanel";
import RuleLabConsole, { consoleTextToLines } from "../components/RuleLabConsole";
import FaultCodeSelect from "../components/FaultCodeSelect";
import ModelScopePicker from "../components/ModelScopePicker";
import { useTheme } from "../contexts/theme-context";
import { apiFetch, fetchAuthMe } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { displayRuleName, formatRuleLabel } from "../lib/ruleDisplay";
import { useModelScope } from "../lib/useModelScope";
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
  const [brickClass, setBrickClass] = useState("");
  const [brickTypes, setBrickTypes] = useState<string[]>([]);
  const [saved, setSaved] = useState<SavedRule[]>([]);
  const [activeRuleId, setActiveRuleId] = useState<string>("");
  const [authRole, setAuthRole] = useState<string | null>(null);
  const [testLimit, setTestLimit] = useState("120");
  const [lookbackHours, setLookbackHours] = useState("24");
  const [testSensorKey, setTestSensorKey] = useState("");
  const [faultCode, setFaultCode] = useState("");
  const [dirty, setDirty] = useState(false);
  const lintTimer = useRef<number | null>(null);
  const scope = useModelScope("demo", brickClass);

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

  const loadBrickTypes = useCallback(async () => {
    const tree = await apiFetch<{ brick_types?: string[] }>("/api/model/tree");
    const types = (tree.brick_types || []).filter((t) => String(t).trim());
    setBrickTypes(types.sort((a, b) => a.localeCompare(b)));
  }, []);

  const loadRuleSource = useCallback(async (ruleId: string) => {
    const res = await apiFetch<{ code: string; path: string }>(`/api/rules/saved/${ruleId}/source`);
    setCode(res.code || DEFAULT_RULE);
    setSourcePath(res.path || "");
  }, []);

  useEffect(() => {
    void refreshSaved();
    void loadBrickTypes();
  }, [refreshSaved, loadBrickTypes]);

  useEffect(() => {
    if (!scope.equipmentId) {
      setTestSensorKey("");
      return;
    }
    if (!scope.sensors.length) {
      setTestSensorKey("");
      return;
    }
    if (!scope.sensors.some((s) => s.point_id === testSensorKey)) {
      setTestSensorKey(scope.sensors[0].point_id);
    }
  }, [scope.equipmentId, scope.sensors, brickClass]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeSensor = scope.sensors.find((s) => s.point_id === testSensorKey);

  const testScopeLabel = useMemo(() => {
    const eq = scope.activeEquipment;
    if (eq?.name) {
      return `${scope.siteId} · ${eq.name}${eq.bacnet_device_instance != null ? ` (dev ${eq.bacnet_device_instance})` : ""}`;
    }
    return scope.siteId || "site";
  }, [scope.siteId, scope.activeEquipment]);

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
    setBusy(true);
    setConsoleText("");
    try {
      const limit = Number(testLimit);
      if (mode === "rule") {
        if (!testSensorKey) {
          setConsoleText("Pick a site, device, and sensor before testing.");
          return;
        }
        const pointKeys = [testSensorKey];
        const sensor = activeSensor;
        const res = await apiFetch<{
          ok?: boolean;
          rows: number;
          flagged: number;
          data_source?: string;
          site_id?: string;
          equipment_id?: string;
          value_column?: string;
          scope_columns?: string[];
          scope_warning?: string;
          events: { type: string; text?: string; status?: string; row?: number; trace?: string }[];
          trace?: string;
          error?: string;
          ms?: number;
        }>("/api/playground/test-rule", {
          method: "POST",
          body: JSON.stringify({
            code,
            config: configFromRecord(cfg),
            site_id: scope.siteId || undefined,
            equipment_id: scope.equipmentId || undefined,
            point_keys: pointKeys,
            lookback_hours: Number(lookbackHours) || 24,
            limit: Number.isFinite(limit) ? limit : 120,
            chunk_hours: 0,
          }),
        });
        const header = [
          `>>> Test — ${testScopeLabel}`,
          sensor ? `sensor: ${sensor.label} (${sensor.timeseries_column})` : "",
          res.value_column ? `feather column: ${res.value_column}` : "",
          `rows=${res.rows} flagged=${res.flagged} · ${res.data_source} (${res.ms ?? 0} ms)`,
          res.scope_warning ? `⚠ ${res.scope_warning}` : "",
        ]
          .filter(Boolean)
          .join("\n");
        const body = formatRuleTestEvents(res.events || [], { maxLines: 28 });
        const trace = res.trace || res.error || "";
        setConsoleText([header, body, trace].filter(Boolean).join("\n\n"));
      } else {
        const res = await apiFetch<{
          ok: boolean;
          stdout?: string;
          error?: string;
          trace?: string;
          data_source?: string;
          site_id?: string;
          flag_columns?: string[];
          preview?: Record<string, unknown>[];
        }>("/api/playground/run-script", {
          method: "POST",
          body: JSON.stringify({ code, limit: Number.isFinite(limit) ? limit : 500 }),
        });
        if (!res.ok) {
          setConsoleText([res.error || "script failed", res.trace || ""].filter(Boolean).join("\n\n"));
        } else {
          setConsoleText(
            [
              `>>> Script test — site=${res.site_id} source=${res.data_source}`,
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
      setConsoleText(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveRule() {
    if (syntaxOk === false) {
      appendConsole("Cannot save — fix syntax errors first.");
      return;
    }
    setBusy(true);
    try {
      let bindingsSource: SavedRule["bindings"] | undefined;
      if (activeRuleId) {
        try {
          const fresh = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
          const live = fresh.rules?.find((r) => r.id === activeRuleId);
          bindingsSource = live?.bindings;
        } catch {
          const existing = saved.find((r) => r.id === activeRuleId);
          bindingsSource = existing?.bindings;
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
        appendConsole(`>>> Created rule "${formatRuleLabel(res.rule.name)}". Map points on FDD assignments.`);
      }
      setDirty(false);
      await refreshSaved();
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function updateAllRecords() {
    if (syntaxOk === false && activeRuleId) {
      appendConsole("Save a valid rule before batch update.");
      return;
    }
    setBusy(true);
    try {
      if (dirty && activeRuleId) {
        await saveRule();
      }
      const res = await apiFetch<{
        rules_run?: number;
        site_runs?: number;
        flagged_runs?: number;
        error_runs?: number;
        ms?: number;
        lookback_hours?: number | null;
        runs?: { rule_name?: string; site_id?: string; flagged?: number; status?: string; error?: string; rows?: number }[];
      }>("/api/rules/batch", {
        method: "POST",
        body: JSON.stringify({
          limit: 50000,
          chunk_hours: 0,
          lookback_hours: 1,
          use_chunks: false,
        }),
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
    setBrickClass("");
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
    setBrickClass("");
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
            Edit on-disk <code>.py</code> rules. Map points on{" "}
            <a href="/fdd-assignments">FDD assignments</a>, <a href="/data-model">Data Model</a>, or{" "}
            <a href="/plot">Trend plot</a> (right-click). <strong>Test</strong> uses one sensor from feather
            data (same historian as <a href="/plot">Trend plot</a>).
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
                const rule = saved.find((r) => r.id === id);
                if (rule) selectRule(rule);
              }}
            >
              {!activeRuleId ? (
                <option value="">New rule (unsaved)</option>
              ) : null}
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
            <label className="field-label" htmlFor="rule-brick-class">
              Test filter (BRICK class)
            </label>
            <select
              id="rule-brick-class"
              value={brickClass}
              onChange={(e) => {
                setBrickClass(e.target.value);
                markDirty();
              }}
            >
              <option value="">— Select class —</option>
              {brickClass && !brickTypes.includes(brickClass) ? (
                <option value={brickClass}>{brickClass}</option>
              ) : null}
              {brickTypes.map((bt) => (
                <option key={bt} value={bt}>
                  {bt}
                </option>
              ))}
            </select>
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
              onChange={(code) => {
                setFaultCode(code);
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
          <div className="field">
            <label className="field-label" htmlFor="test-limit">
              Test rows
            </label>
            <input id="test-limit" value={testLimit} onChange={(e) => setTestLimit(e.target.value)} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="test-lookback">
              Lookback (h)
            </label>
            <input id="test-lookback" value={lookbackHours} onChange={(e) => setLookbackHours(e.target.value)} />
          </div>
        </div>

        <div className="panel rule-lab-test-scope">
          <h3 className="panel-title">Test against one sensor</h3>
          {scope.error ? <p className="error">{scope.error}</p> : null}
          <div className="form-row model-scope-row">
            <ModelScopePicker
              idPrefix="rule-test"
              sites={scope.sites}
              siteId={scope.siteId}
              onSiteChange={scope.setSiteId}
              equipment={scope.equipment}
              equipmentId={scope.equipmentId}
              onEquipmentChange={scope.setEquipmentId}
              sensors={scope.sensors}
              sensorPointId={testSensorKey}
              onSensorChange={setTestSensorKey}
              disabled={scope.loading}
              queryEngine={scope.queryEngine}
            />
            <div className="form-row-actions">
              <a
                className="secondary-btn"
                href={`/plot?site=${encodeURIComponent(scope.siteId)}&device=${encodeURIComponent(scope.equipmentId)}`}
              >
                Trend plot
              </a>
            </div>
          </div>
          {activeSensor ? (
            <p className="muted">
              Timeseries column: <code>{activeSensor.timeseries_column}</code>
              {activeSensor.series_id ? (
                <>
                  {" "}
                  · series <code>{activeSensor.series_id}</code>
                </>
              ) : null}
            </p>
          ) : null}
        </div>

        {mode === "rule" ? <RuleConfigPanel config={cfg} onChange={onCfgChange} /> : null}

        <div className="toolbar rule-lab-actions">
          <button type="button" className="secondary" disabled={busy} onClick={() => void lintNow()}>
            Lint
          </button>
          <button type="button" disabled={busy || syntaxOk === false} onClick={() => void testRun()}>
            Test
          </button>
          <button type="button" disabled={busy || authRole === "operator"} onClick={() => void saveRule()}>
            {activeRuleId ? "Update rule .py" : "Save rule .py"}
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || authRole === "operator"}
            onClick={() => void updateAllRecords()}
            title="Run all saved rules against feather data and update check-engine records"
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
        <PythonCodeEditor value={code} onChange={onCodeChange} height="420px" lintIssues={lintIssues} />
      </div>

      <RuleLabConsole
        lines={consoleLines}
        placeholder="Lint or Test — errors and tracebacks appear here."
        footer={
          <button type="button" className="secondary small-btn" onClick={() => setConsoleText("")}>
            Clear
          </button>
        }
      />
    </div>
  );
}
