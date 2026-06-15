import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PageHeader from "../components/PageHeader";
import FddRuleTestPanel from "../components/FddRuleTestPanel";
import PythonCodeEditor from "../components/PythonCodeEditor";
import RuleLabConsole, { consoleTextToLines } from "../components/RuleLabConsole";
import { apiDownloadBlob, apiFetch, fetchAuthMe, getBridgeBase } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { openTextPopup } from "../lib/ttlPopup";
import { displayRuleName, formatRuleLabel } from "../lib/ruleDisplay";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import {
  formatBatchSummary,
  formatLintIssues,
  formatRuleTestEvents,
  type LintIssue,
} from "../lib/rule-lab-console";

const NEW_RULE_VALUE = "__new__";

type RuleBackend = "arrow" | "datafusion_sql";

const SQL_THRESHOLD_TEMPLATE = `SELECT
  *,
  zone_temp > 75.0 AS fault
FROM telemetry`;

const SQL_CASE_TEMPLATE = `SELECT
  *,
  CASE
    WHEN fan_cmd > 0.5 AND airflow_cfm < 1000.0 THEN true
    ELSE false
  END AS fault
FROM telemetry`;

type SavedRule = {
  id: string;
  name: string;
  mode: "rule" | "script";
  backend?: RuleBackend | string;
  severity: string;
  enabled: boolean;
  source_path?: string;
  fault_code?: string;
  fault_codes?: string[];
  code?: string;
  sql?: string;
  fault_column?: string;
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
  const activeSiteId = useActiveSiteId();
  const [code, setCode] = useState("");
  const [sql, setSql] = useState(SQL_THRESHOLD_TEMPLATE);
  const [ruleBackend, setRuleBackend] = useState<RuleBackend>("arrow");
  const [faultColumn, setFaultColumn] = useState("fault");
  const [sqlLintIssues, setSqlLintIssues] = useState<LintIssue[]>([]);
  const [sqlSyntaxOk, setSqlSyntaxOk] = useState<boolean | null>(null);
  const [sqlPreview, setSqlPreview] = useState<Record<string, unknown> | null>(null);
  const [sourcePath, setSourcePath] = useState("");
  const [consoleText, setConsoleText] = useState("");
  const [busy, setBusy] = useState(false);
  const [lintBusy, setLintBusy] = useState(false);
  const [syntaxOk, setSyntaxOk] = useState<boolean | null>(null);
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [ruleName, setRuleName] = useState("New rule");
  const [saved, setSaved] = useState<SavedRule[]>([]);
  const [activeRuleId, setActiveRuleId] = useState<string>("");
  const [creatingNew, setCreatingNew] = useState(true);
  const [authRole, setAuthRole] = useState<string | null>(null);
  const [metaDirty, setMetaDirty] = useState(false);
  const [helperSource, setHelperSource] = useState("");
  const [helperWarnings, setHelperWarnings] = useState<string[]>([]);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const lintTimer = useRef<number | null>(null);

  useEffect(() => {
    fetchAuthMe()
      .then((me) => setAuthRole(me.role))
      .catch(() => setAuthRole(null));
  }, []);

  const refreshSaved = useCallback(async () => {
    const res = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
    const rules = (res.rules || []).filter((r) => r.mode !== "script");
    setSaved(rules);
    return rules;
  }, []);

  const loadRuleView = useCallback(async (rule: SavedRule) => {
    setCreatingNew(false);
    setActiveRuleId(rule.id);
    setRuleName(displayRuleName(rule.name));
    setMetaDirty(false);
    const backend = (rule.backend === "datafusion_sql" ? "datafusion_sql" : "arrow") as RuleBackend;
    setRuleBackend(backend);
    setFaultColumn(rule.fault_column || "fault");
    if (backend === "datafusion_sql") {
      setSql(rule.sql?.trim() || SQL_THRESHOLD_TEMPLATE);
      setCode(rule.code?.trim() || "# DataFusion SQL rule — see sql field");
      setSourcePath("");
      setHelperSource("");
      setHelperWarnings([]);
      return;
    }
    try {
      const res = await apiFetch<{ code: string; path: string }>(`/api/rules/saved/${rule.id}/source`);
      setCode(res.code?.trim() || rule.code?.trim() || "");
      setSourcePath(res.path || rule.source_path || "");
      if (rule.id) {
        try {
          const expanded = await apiFetch<{
            imports?: { module: string; source?: string; warning?: string }[];
            warnings?: string[];
          }>(`/api/playground/rules/${rule.id}/source-expanded`);
          const blocks = (expanded.imports || [])
            .filter((i) => i.source)
            .map((i) => `# ${i.module}\n${i.source}`);
          setHelperSource(blocks.join("\n\n"));
          setHelperWarnings(expanded.warnings || []);
        } catch {
          setHelperSource("");
          setHelperWarnings([]);
        }
      }
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
          await loadRuleView(rules[0]);
        } else {
          setCreatingNew(true);
          setActiveRuleId("");
          setCode("");
          setSourcePath("");
        }
      } catch (e) {
        setConsoleText(formatApiError(e));
      } finally {
        setInitialLoadDone(true);
      }
    })();
  }, [refreshSaved, loadRuleView]);

  const runDebouncedLint = useCallback((source: string) => {
    if (!source.trim()) {
      setSyntaxOk(null);
      setLintIssues([]);
      return;
    }
    if (lintTimer.current) window.clearTimeout(lintTimer.current);
    lintTimer.current = window.setTimeout(() => {
      setLintBusy(true);
      apiFetch<{ ok: boolean; issues: LintIssue[] }>("/api/playground/lint", {
        method: "POST",
        body: JSON.stringify({ code: source, mode: "rule" }),
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
  }, []);

  const runDebouncedSqlLint = useCallback((source: string) => {
    if (!source.trim()) {
      setSqlSyntaxOk(null);
      setSqlLintIssues([]);
      return;
    }
    if (lintTimer.current) window.clearTimeout(lintTimer.current);
    lintTimer.current = window.setTimeout(() => {
      setLintBusy(true);
      apiFetch<{ ok: boolean; issues: LintIssue[] }>("/api/rules/lab/lint-sql", {
        method: "POST",
        body: JSON.stringify({ backend: "datafusion_sql", sql: source, fault_column: faultColumn }),
      })
        .then((res) => {
          setSqlSyntaxOk(res.ok);
          setSqlLintIssues(res.issues || []);
        })
        .catch(() => {
          setSqlSyntaxOk(null);
          setSqlLintIssues([]);
        })
        .finally(() => setLintBusy(false));
    }, 400);
  }, [faultColumn]);

  useEffect(() => {
    if (ruleBackend === "datafusion_sql") {
      runDebouncedSqlLint(sql);
      return () => {
        if (lintTimer.current) window.clearTimeout(lintTimer.current);
      };
    }
    runDebouncedLint(code);
    return () => {
      if (lintTimer.current) window.clearTimeout(lintTimer.current);
    };
  }, [code, sql, ruleBackend, runDebouncedLint, runDebouncedSqlLint]);

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

  async function validateSql() {
    if (!sql.trim()) {
      appendConsole("Enter SQL before validating.");
      return;
    }
    setBusy(true);
    try {
      const res = await apiFetch<{
        ok: boolean;
        error?: string;
        details?: string;
        true_count?: number;
        false_count?: number;
        row_count?: number;
        datafusion_installed?: boolean;
      }>("/api/rules/lab/validate", {
        method: "POST",
        body: JSON.stringify({
          backend: "datafusion_sql",
          sql,
          fault_column: faultColumn,
          site_id: activeSiteId || undefined,
          limit: 500,
        }),
      });
      setSqlSyntaxOk(res.ok);
      if (res.ok) {
        appendConsole(
          `>>> SQL valid · rows=${res.row_count} true=${res.true_count} false=${res.false_count}`,
        );
      } else {
        appendConsole([res.error, res.details].filter(Boolean).join("\n"));
      }
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function previewSql() {
    if (!sql.trim()) return;
    setBusy(true);
    setConsoleText("");
    try {
      const res = await apiFetch<Record<string, unknown>>("/api/rules/lab/preview", {
        method: "POST",
        body: JSON.stringify({
          backend: "datafusion_sql",
          sql,
          fault_column: faultColumn,
          site_id: activeSiteId || undefined,
          limit: 500,
        }),
      });
      setSqlPreview(res);
      if (res.ok) {
        setConsoleText(
          [
            ">>> DataFusion SQL preview",
            `backend: datafusion_sql · rows=${res.row_count} · true=${res.true_count} (${res.fault_rate_pct}%)`,
            `null=${res.null_count} · ${res.ms ?? res.duration_ms} ms · ${res.data_source}`,
            Array.isArray(res.preview) && res.preview.length
              ? `fault preview: ${JSON.stringify(res.preview.slice(0, 5), null, 2)}`
              : "",
          ]
            .filter(Boolean)
            .join("\n"),
        );
      } else {
        setConsoleText(String(res.error || res.details || "SQL preview failed"));
      }
    } catch (e) {
      setConsoleText(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function compareBackends() {
    if (ruleBackend !== "datafusion_sql" || !sql.trim() || !code.trim()) {
      appendConsole("Compare needs a PyArrow code buffer and DataFusion SQL rule.");
      return;
    }
    setBusy(true);
    try {
      const res = await apiFetch<{
        ok: boolean;
        left_true_count?: number;
        right_true_count?: number;
        matching_rows?: number;
        mismatching_rows?: number;
        error?: string;
      }>("/api/rules/lab/compare", {
        method: "POST",
        body: JSON.stringify({
          left: { backend: "arrow", code },
          right: { backend: "datafusion_sql", sql, fault_column: faultColumn },
          site_id: activeSiteId || undefined,
          limit: 1000,
        }),
      });
      if (res.ok) {
        appendConsole(
          `>>> Compare arrow vs SQL · left=${res.left_true_count} right=${res.right_true_count} mismatches=${res.mismatching_rows}`,
        );
      } else {
        appendConsole(res.error || "Compare failed");
      }
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveSqlRule() {
    setBusy(true);
    try {
      const res = await apiFetch<{ rule: SavedRule }>("/api/rules/lab/save", {
        method: "POST",
        body: JSON.stringify({
          id: creatingNew ? undefined : activeRuleId || undefined,
          name: ruleName,
          mode: "rule",
          backend: "datafusion_sql",
          sql,
          fault_column: faultColumn,
          code: "# DataFusion SQL rule — see sql field",
          config: {},
          severity: "warning",
          enabled: false,
        }),
      });
      setActiveRuleId(res.rule.id);
      setCreatingNew(false);
      setMetaDirty(false);
      appendConsole(`>>> Saved DataFusion SQL rule ${res.rule.id}`);
      await refreshSaved();
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function lintNow() {
    if (ruleBackend === "datafusion_sql") {
      await validateSql();
      return;
    }
    if (!code.trim()) {
      appendConsole("No rule loaded — upload rule.py or select a saved rule.");
      return;
    }
    setBusy(true);
    try {
      const res = await apiFetch<{ ok: boolean; issues: LintIssue[] }>("/api/playground/lint", {
        method: "POST",
        body: JSON.stringify({ code, mode: "rule" }),
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
    if (ruleBackend === "datafusion_sql") {
      await previewSql();
      return;
    }
    if (!code.trim()) {
      appendConsole("Upload rule.py before testing.");
      return;
    }
    if (syntaxOk === false) {
      appendConsole("Fix lint errors before test.");
      return;
    }
    const rule = saved.find((r) => r.id === activeRuleId);
    const pointId = rule?.bindings?.point_ids?.[0];
    if (!pointId) {
      appendConsole(
        `Quick test needs one bound point — pin "${displayRuleName(rule?.name ?? "")}" (${activeRuleId}) on a point in Model & assignments (fdd_rule_ids), then import.`,
      );
      return;
    }
    setBusy(true);
    setConsoleText("");
    try {
      const res = await apiFetch<{
        rows: number;
        flagged: number;
        data_source?: string;
        value_column?: string;
        backend?: string;
        events: { type: string; text?: string }[];
        trace?: string;
        error?: string;
        ms?: number;
      }>("/api/playground/test-rule", {
        method: "POST",
        body: JSON.stringify({
          code,
          config: {},
          site_id: activeSiteId || undefined,
          point_keys: [pointId],
          lookback_hours: 3,
          limit: 120,
          chunk_hours: 0,
        }),
      });
      setConsoleText(
        [
          `>>> Quick test (first bound point) rows=${res.rows} flagged=${res.flagged} · ${res.data_source}`,
          res.backend ? `backend: ${res.backend}${res.ms != null ? ` · ${res.ms} ms` : ""}` : "",
          res.value_column ? `column: ${res.value_column}` : "",
          formatRuleTestEvents(res.events || [], { maxLines: 28 }),
          res.trace || res.error || "",
        ]
          .filter(Boolean)
          .join("\n\n"),
      );
    } catch (e) {
      setConsoleText(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveMetadata(opts?: { manageBusy?: boolean }) {
    if (!activeRuleId || creatingNew) {
      appendConsole("Upload rule.py first to create a rule.");
      return;
    }
    if (ruleBackend === "datafusion_sql") {
      if (!sql.trim()) return;
    } else if (!code.trim()) {
      return;
    }
    const manageBusy = opts?.manageBusy !== false;
    if (manageBusy) setBusy(true);
    try {
      const fresh = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
      const existing = fresh.rules?.find((r) => r.id === activeRuleId);
      const bindingsSource = existing?.bindings;
      if (ruleBackend === "datafusion_sql") {
        const res = await apiFetch<{ rule: SavedRule }>("/api/rules/lab/save", {
          method: "POST",
          body: JSON.stringify({
            id: activeRuleId,
            name: ruleName,
            mode: "rule",
            backend: "datafusion_sql",
            sql,
            fault_column: faultColumn,
            code: code.trim() || "# DataFusion SQL rule — see sql field",
            config: existing?.config ?? {},
            severity: existing?.severity ?? "warning",
            enabled: existing?.enabled ?? false,
            bindings: preservedBindings(bindingsSource),
          }),
        });
        setMetaDirty(false);
        appendConsole(`>>> Saved name for ${res.rule.id}`);
        await refreshSaved();
        return;
      }
      const res = await apiFetch<{ rule: SavedRule }>("/api/rules/save", {
        method: "POST",
        body: JSON.stringify({
          id: activeRuleId,
          name: ruleName,
          mode: "rule",
          code,
          config: {},
          severity: "warning",
          bindings: preservedBindings(bindingsSource),
        }),
      });
      setMetaDirty(false);
      appendConsole(`>>> Saved name for ${res.rule.id}`);
      await refreshSaved();
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      if (manageBusy) setBusy(false);
    }
  }

  async function downloadAllRulesKit() {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (activeSiteId) params.set("site_id", activeSiteId);
      params.set("lookback_hours", "3");
      appendConsole(">>> Building export-all rules zip…");
      const { blob, filename } = await apiDownloadBlob(`/api/rules/export-all-kit?${params.toString()}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      appendConsole(`>>> Downloaded ${filename} (all rules bundle)`);
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function downloadKit() {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (activeSiteId) params.set("site_id", activeSiteId);
      if (activeRuleId && !creatingNew) params.set("rule_id", activeRuleId);
      params.set("lookback_hours", "3");
      const rule = saved.find((r) => r.id === activeRuleId);
      const pointId = rule?.bindings?.point_ids?.[0];
      if (pointId) params.set("point_id", pointId);
      const { blob, filename } = await apiDownloadBlob(`/api/rules/export-kit?${params.toString()}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      appendConsole(`>>> Downloaded ${filename} (rule.py + data.py + sample.feather)`);
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUploadFile(file: File | null) {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      if (activeRuleId && !creatingNew) form.append("rule_id", activeRuleId);
      const base = getBridgeBase();
      const token = sessionStorage.getItem("ofdd_token");
      const res = await fetch(`${base}/api/rules/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      const text = await res.text();
      if (!res.ok) {
        let msg = text;
        try {
          const body = JSON.parse(text) as { detail?: string };
          if (body.detail) msg = body.detail;
        } catch {
          /* plain text */
        }
        throw new Error(msg);
      }
      const body = JSON.parse(text) as { rule: SavedRule; filename?: string };
      const newId = body.rule.id;
      setActiveRuleId(newId);
      setCreatingNew(false);
      await loadRuleView(body.rule);
      appendConsole(
        `>>> Uploaded ${body.filename || file.name} → ${formatRuleLabel(body.rule.name)} (${newId})`,
      );
      await refreshSaved();
    } catch (e) {
      appendConsole(formatApiError(e));
    } finally {
      setBusy(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  }

  async function updateAllRecords() {
    setBusy(true);
    try {
      if (metaDirty && activeRuleId) await saveMetadata({ manageBusy: false });
      const res = await apiFetch<{
        rules_run?: number;
        flagged_runs?: number;
        runs?: { rule_name?: string; site_id?: string; flagged?: number; status?: string }[];
      }>("/api/rules/batch", {
        method: "POST",
        body: JSON.stringify({ limit: 50000, chunk_hours: 6, lookback_hours: 24, use_chunks: true }),
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
    setCode("");
    setSql(SQL_THRESHOLD_TEMPLATE);
    setRuleBackend("arrow");
    setSourcePath("");
    setMetaDirty(false);
    appendConsole("Download a blank kit, upload rule.py (PyArrow), or switch to DataFusion SQL.");
  }

  function onBackendChange(next: RuleBackend) {
    setRuleBackend(next);
    setMetaDirty(true);
    if (next === "datafusion_sql" && !sql.trim()) {
      setSql(SQL_THRESHOLD_TEMPLATE);
    }
  }

  async function removeRule() {
    if (!activeRuleId) return;
    if (!window.confirm(`Delete rule "${ruleName}"?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/rules/saved/${activeRuleId}`, { method: "DELETE" });
      const list = await refreshSaved();
      if (list[0]) await loadRuleView(list[0]);
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
    if (rule) await loadRuleView(rule);
  }

  function openRuleInTab() {
    if (!code.trim()) return;
    const title = sourcePath ? sourcePath.split("/").pop() || "rule.py" : "rule.py";
    openTextPopup(title, code);
  }

  const selectValue = creatingNew ? NEW_RULE_VALUE : activeRuleId || saved[0]?.id || "";

  const activeLintIssues = ruleBackend === "datafusion_sql" ? sqlLintIssues : lintIssues;
  const activeSyntaxOk = ruleBackend === "datafusion_sql" ? sqlSyntaxOk : syntaxOk;

  const syntaxTitle = useMemo(() => {
    if (lintBusy) return "Checking syntax…";
    if (activeSyntaxOk === true) return ruleBackend === "datafusion_sql" ? "SQL lint OK" : "Arrow lint OK";
    if (activeSyntaxOk === false)
      return activeLintIssues.find((i) => i.severity === "error")?.message || "Lint error";
    const hasSource = ruleBackend === "datafusion_sql" ? sql.trim() : code.trim();
    return hasSource ? "Lint pending" : "No rule loaded";
  }, [lintBusy, activeSyntaxOk, activeLintIssues, code, sql, ruleBackend]);

  const consoleLines = useMemo(() => consoleTextToLines(consoleText), [consoleText]);

  return (
    <div className="page page-wide rule-lab-page">
      <PageHeader
        title="Rule Lab"
        subtitle={
          <>
            Arrow-only rules: <strong>download kit</strong> → edit locally → <strong>upload rule.py</strong>, or author{" "}
            <strong>DataFusion SQL</strong> (server-side, optional extra).
            Pin rules on the <a href="/model">Data Model</a> commissioning JSON or test by equipment below.
          </>
        }
      />

      {authRole === "operator" ? (
        <p className="error panel">
          Signed in as <strong>operator</strong>. Upload and batch require <strong>integrator</strong> or{" "}
          <strong>agent</strong> (download kit and read-only view are OK).
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
              {creatingNew ? <option value={NEW_RULE_VALUE}>New rule (upload .py)</option> : null}
              {saved.map((r) => (
                <option key={r.id} value={r.id}>
                  {formatRuleLabel(r.name)}
                  {metaDirty && r.id === activeRuleId ? " *" : ""}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="rule-step-btn rule-step-add"
              disabled={busy}
              onClick={beginNewRule}
              title="New rule"
              aria-label="Add rule"
            >
              +
            </button>
          </div>
          <span className={syntaxPillClass(activeSyntaxOk, lintBusy)} title={syntaxTitle}>
            {lintBusy ? "…" : activeSyntaxOk === true ? (ruleBackend === "datafusion_sql" ? "sql ok" : "arrow ok") : activeSyntaxOk === false ? "lint err" : ruleBackend === "datafusion_sql" ? "sql —" : "arrow —"}
          </span>
        </div>

        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="rule-backend">
              Rule backend
            </label>
            <select
              id="rule-backend"
              value={ruleBackend}
              disabled={busy}
              onChange={(e) => onBackendChange(e.target.value as RuleBackend)}
            >
              <option value="arrow">PyArrow</option>
              <option value="datafusion_sql">DataFusion SQL</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="rule-name">
              Name
            </label>
            <input
              id="rule-name"
              value={ruleName}
              disabled={creatingNew}
              onChange={(e) => {
                setRuleName(e.target.value);
                setMetaDirty(true);
              }}
            />
          </div>
        </div>

        <p className="muted rule-lab-hint">
          {ruleBackend === "datafusion_sql" ? (
            <>
              DataFusion SQL rules run <strong>server-side</strong> against the Arrow table <code>telemetry</code>. The query
              must return one boolean column named <code>{faultColumn}</code>. Install optional extra:{" "}
              <code>open-fdd[datafusion]</code>.
            </>
          ) : (
            <>
              Tune thresholds in <code>rule.py</code> constants (<code>VALUE_COLUMN</code>, limits) — download kit, edit
              locally, upload.
            </>
          )}
        </p>

        <div className="toolbar rule-lab-actions">
          {ruleBackend === "arrow" ? (
            <>
              <button type="button" className="secondary" disabled={busy} onClick={() => void downloadKit()}>
                Download kit (.zip)
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || authRole === "operator"}
                onClick={() => void downloadAllRulesKit()}
              >
                Export all rules
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || authRole === "operator"}
                onClick={() => uploadRef.current?.click()}
              >
                Upload rule.py
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => {
                  setSql(SQL_THRESHOLD_TEMPLATE);
                  setMetaDirty(true);
                }}
              >
                Threshold template
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => {
                  setSql(SQL_CASE_TEMPLATE);
                  setMetaDirty(true);
                }}
              >
                CASE template
              </button>
              <button type="button" className="secondary" disabled={busy || authRole === "operator"} onClick={() => void saveSqlRule()}>
                Save SQL rule
              </button>
              <button type="button" className="secondary" disabled={busy || !code.trim() || !sql.trim()} onClick={() => void compareBackends()}>
                Compare backends
              </button>
            </>
          )}
          <input
            ref={uploadRef}
            type="file"
            accept=".py,text/x-python,application/x-python-code"
            hidden
            onChange={(e) => void onUploadFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="secondary"
            disabled={busy || (ruleBackend === "arrow" ? !code.trim() : !sql.trim())}
            onClick={() => void lintNow()}
          >
            {ruleBackend === "datafusion_sql" ? "Validate SQL" : "Lint"}
          </button>
          <button
            type="button"
            disabled={
              busy ||
              activeSyntaxOk === false ||
              (ruleBackend === "arrow" ? !code.trim() : !sql.trim())
            }
            onClick={() => void testRun()}
          >
            {ruleBackend === "datafusion_sql" ? "Run Preview" : "Quick test"}
          </button>
          <button
            type="button"
            disabled={busy || authRole === "operator" || creatingNew || !metaDirty}
            onClick={() => void saveMetadata()}
          >
            Save name
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || authRole === "operator" || (ruleBackend === "arrow" ? !code.trim() : false)}
            onClick={() => void updateAllRecords()}
          >
            Update all records
          </button>
          {metaDirty ? <span className="muted dirty-hint">Unsaved name</span> : null}
        </div>
      </div>

      {sourcePath ? (
        <details className="muted code-path">
          <summary>Rule file metadata</summary>
          <code>{sourcePath.split("/").pop() || "rule.py"}</code>
        </details>
      ) : null}

      <FddRuleTestPanel rules={saved} disabled={busy || authRole === "operator"} />

      <div className="panel rule-lab-readonly-panel">
        <h3 className="panel-title">{ruleBackend === "datafusion_sql" ? "SQL rule editor" : "Rule source"}</h3>
        {ruleBackend === "datafusion_sql" ? (
          <>
            <label className="field-label" htmlFor="fault-column">
              Fault column
            </label>
            <input
              id="fault-column"
              value={faultColumn}
              disabled={busy}
              onChange={(e) => {
                setFaultColumn(e.target.value);
                setMetaDirty(true);
              }}
            />
            <textarea
              className="sql-rule-editor"
              rows={14}
              value={sql}
              disabled={busy || authRole === "operator"}
              onChange={(e) => {
                setSql(e.target.value);
                setMetaDirty(true);
              }}
              spellCheck={false}
            />
            {sqlPreview?.ok === false && sqlPreview.datafusion_installed === false ? (
              <p className="error panel">
                DataFusion SQL backend is not installed on this Open-FDD runtime. Install{" "}
                <code>open-fdd[datafusion]</code>.
              </p>
            ) : null}
          </>
        ) : code.trim() ? (
          <div className="rule-readonly-editor">
            <PythonCodeEditor
              value={code}
              onChange={() => undefined}
              readOnly
              height="320px"
              lintIssues={lintIssues}
            />
          </div>
        ) : (
          <p className="muted">
            No rule loaded. Download a dev kit with real feather sample data, edit <code>rule.py</code> locally with{" "}
            <code>pip install open-fdd pyarrow</code>, then upload when lint passes.
          </p>
        )}
        {activeLintIssues.length > 0 && activeSyntaxOk === false ? (
          <ul className="rule-lint-list">
            {activeLintIssues
              .filter((i) => i.severity === "error")
              .slice(0, 6)
              .map((i, idx) => (
                <li key={`${i.line}-${idx}`}>
                  {i.line ? `line ${i.line}: ` : ""}
                  {i.message}
                </li>
              ))}
          </ul>
        ) : null}
        {ruleBackend === "datafusion_sql" && sqlPreview?.ok ? (
          <p className="muted">
            Backend: <strong>DataFusion SQL</strong> · rows={String(sqlPreview.row_count)} · fault rate{" "}
            {String(sqlPreview.fault_rate_pct)}%
          </p>
        ) : null}
      </div>

      {ruleBackend === "arrow" && (helperSource || helperWarnings.length) ? (
        <details className="panel rule-lab-readonly-panel">
          <summary>Helper libraries (Open-FDD + PyArrow)</summary>
          {helperSource ? (
            <>
              <p className="muted">Expanded imports for review — included in download zip as working source.</p>
              <pre className="rule-helper-source">{helperSource}</pre>
            </>
          ) : (
            <p className="muted">{helperWarnings.join(" · ")}</p>
          )}
        </details>
      ) : null}

      <RuleLabConsole
        lines={consoleLines}
        placeholder="Download, upload, lint, quick test, or batch output."
        footer={
          <button type="button" className="secondary small-btn" onClick={() => setConsoleText("")}>
            Clear
          </button>
        }
      />
    </div>
  );
}
