import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PythonCodeEditor from "../components/PythonCodeEditor";
import PageHeader from "../components/PageHeader";
import RuleConfigPanel, { configFromRecord, configToRecord } from "../components/RuleConfigPanel";
import RuleLabConsole, { consoleTextToLines } from "../components/RuleLabConsole";
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

const DEFAULT_RULE = `import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    """Flag when supply air temp exceeds cfg['high']. Column defaults to SAT from feather historian."""
    col = str(cfg.get("column", "SAT"))
    high = float(cfg.get("high", 75.0))
    return pc.greater(table[col], high)
`;

const DEFAULT_SCRIPT = `# df script — set out = {"df": df, "events": [...]}
df = df.copy()
df["custom_flag"] = 0
out = {"df": df, "events": [{"type": "note", "text": "edit me"}]}
`;

const NEW_RULE_VALUE = "__new__";

type Mode = "rule" | "script";

type SavedRule = {
  id: string;
  name: string;
  mode: Mode;
  severity: string;
  enabled: boolean;
  source_path?: string;
  fault_code?: string;
  fault_codes?: string[];
  code?: string;
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
  const [cfg, setCfg] = useState<Record<string, string>>({ high: "75", column: "SAT" });
  const [consoleText, setConsoleText] = useState("");
  const [busy, setBusy] = useState(false);
  const [lintBusy, setLintBusy] = useState(false);
  const [syntaxOk, setSyntaxOk] = useState<boolean | null>(null);
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [ruleName, setRuleName] = useState("Supply air temp high");
  const [saved, setSaved] = useState<SavedRule[]>([]);
  const [activeRuleId, setActiveRuleId] = useState<string>("");
  const [creatingNew, setCreatingNew] = useState(false);
  const [authRole, setAuthRole] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const lintTimer = useRef<number | null>(null);

  useEffect(() => {
    fetchAuthMe()
      .then((me) => setAuthRole(me.role))
      .catch(() => setAuthRole(null));
  }, []);

  const refreshSaved = useCallback(async () => {
    const res = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
    const rules = res.rules || [];
    setSaved(rules);
    return rules;
  }, []);

  const loadRuleIntoEditor = useCallback(async (rule: SavedRule) => {
    setCreatingNew(false);
    setActiveRuleId(rule.id);
    setRuleName(displayRuleName(rule.name));
    setMode(rule.mode);
    setCfg(configToRecord(rule.config || {}));
    setDirty(false);
    try {
      const res = await apiFetch<{ code: string; path: string }>(`/api/rules/saved/${rule.id}/source`);
      setCode(
        res.code?.trim()
          ? res.code
          : rule.code?.trim()
            ? rule.code
            : rule.mode === "script"
              ? DEFAULT_SCRIPT
              : DEFAULT_RULE,
      );
      setSourcePath(res.path || rule.source_path || "");
    } catch (e) {
      if (rule.code?.trim()) {
        setCode(rule.code);
        setSourcePath(rule.source_path || "");
      } else {
        setConsoleText(formatApiError(e));
      }
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const rules = await refreshSaved();
        if (rules.length > 0) {
          await loadRuleIntoEditor(rules[0]);
        } else {
          setCreatingNew(true);
          setActiveRuleId("");
        }
      } catch (e) {
        setConsoleText(formatApiError(e));
      } finally {
        setInitialLoadDone(true);
      }
    })();
  }, [refreshSaved, loadRuleIntoEditor]);

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
        "Quick test needs one bound point — add this rule id to points[].fdd_rule_ids in Model & assignments JSON, then import.",
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
          backend?: string;
          fully_arrow_native?: boolean;
          migration_message?: string;
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
            res.backend ? `backend: ${res.backend}${res.ms != null ? ` · ${res.ms} ms` : ""}` : "",
            res.migration_message || "",
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
        severity: "warning",
        bindings: preservedBindings(bindingsSource),
      };
      if (activeRuleId) {
        const saveRes = await apiFetch<{ rule: SavedRule }>("/api/rules/save", {
          method: "POST",
          body: JSON.stringify({ ...payload, id: activeRuleId }),
        });
        setSourcePath(saveRes.rule.source_path || sourcePath);
        appendConsole(`>>> Updated rule .py — ${saveRes.rule.source_path || sourcePath}`);
      } else {
        const res = await apiFetch<{ rule: SavedRule }>("/api/rules/save", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        const newId = res.rule.id;
        setActiveRuleId(newId);
        setCreatingNew(false);
        setSourcePath(res.rule.source_path || "");
        appendConsole(
          `>>> Created rule "${formatRuleLabel(res.rule.name)}" (${newId}). Pin points via Model & assignments → Import / export JSON.`,
        );
        setDirty(false);
        const rules = await refreshSaved();
        const current = rules.find((r) => r.id === newId);
        if (current) await loadRuleIntoEditor(current);
        return;
      }
      setDirty(false);
      const rules = await refreshSaved();
      const current = rules.find((r) => r.id === activeRuleId);
      if (current) await loadRuleIntoEditor(current);
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

  function beginNewRule() {
    setCreatingNew(true);
    setActiveRuleId("");
    setRuleName("New rule");
    setMode("rule");
    setCode(DEFAULT_RULE);
    setCfg({ high: "75" });
    setSourcePath("");
    setDirty(true);
  }

  async function removeRule() {
    if (!activeRuleId) return;
    if (!window.confirm(`Delete rule "${ruleName}"?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/rules/saved/${activeRuleId}`, { method: "DELETE" });
      const list = await refreshSaved();
      if (list[0]) await loadRuleIntoEditor(list[0]);
      else beginNewRule();
      appendConsole(`>>> Deleted rule ${activeRuleId}`);
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function onRuleSelectChange(id: string) {
    if (id === NEW_RULE_VALUE) {
      beginNewRule();
      return;
    }
    const rule = saved.find((r) => r.id === id);
    if (rule) await loadRuleIntoEditor(rule);
  }

  const selectValue = creatingNew ? NEW_RULE_VALUE : activeRuleId || saved[0]?.id || "";

  const syntaxTitle = useMemo(() => {
    if (lintBusy) return "Checking syntax…";
    if (syntaxOk === true) return "Syntax OK";
    if (syntaxOk === false) return lintIssues.find((i) => i.severity === "error")?.message || "Syntax error";
    return "Syntax not checked";
  }, [lintBusy, syntaxOk, lintIssues]);

  const consoleLines = useMemo(() => consoleTextToLines(consoleText), [consoleText]);
  const editorKey = creatingNew ? "new" : activeRuleId || "empty";

  return (
    <div className="page page-wide rule-lab-page">
      <PageHeader
        title="Rule Lab"
        subtitle={
          <>
            Rules use <code>apply_faults_arrow(table, cfg, context)</code> over PyArrow historian columns.
            Pin rules via{" "}
            <a href="/model">Model & assignments</a> commissioning JSON.
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
          <div className="rule-switcher-group">
            <button
              type="button"
              className="rule-step-btn rule-step-remove"
              disabled={!activeRuleId || busy || creatingNew}
              onClick={() => void removeRule()}
              title="Delete selected rule"
              aria-label="Delete rule"
            >
              −
            </button>
            <select
              id="rule-select"
              className="rule-switcher-select"
              value={selectValue}
              disabled={!initialLoadDone || (saved.length === 0 && creatingNew)}
              onChange={(e) => void onRuleSelectChange(e.target.value)}
            >
              {creatingNew ? <option value={NEW_RULE_VALUE}>New rule (draft)</option> : null}
              {saved.map((r) => (
                <option key={r.id} value={r.id}>
                  {formatRuleLabel(r.name)}
                  {dirty && r.id === activeRuleId ? " *" : ""}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="rule-step-btn rule-step-add"
              disabled={busy}
              onClick={beginNewRule}
              title="Create new rule"
              aria-label="Add rule"
            >
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
                if (creatingNew) setCode(m === "rule" ? DEFAULT_RULE : DEFAULT_SCRIPT);
                markDirty();
              }}
            >
              <option value="rule">Arrow / Python rule</option>
              <option value="script">DataFrame script</option>
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
            {activeRuleId && !creatingNew ? "Update rule .py" : "Save rule .py"}
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
        <PythonCodeEditor
          key={editorKey}
          value={code}
          onChange={onCodeChange}
          height="480px"
          lintIssues={lintIssues}
        />
      </div>

      <RuleLabConsole
        lines={consoleLines}
        placeholder="Lint, quick test, batch output, or save status."
        footer={
          <button type="button" className="secondary small-btn" onClick={() => setConsoleText("")}>
            Clear
          </button>
        }
      />
    </div>
  );
}
