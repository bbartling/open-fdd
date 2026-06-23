import { useCallback, useEffect, useMemo, useState } from "react";
import ModelScopePicker from "./ModelScopePicker";
import RuleLabConsole, { consoleTextToLines } from "./RuleLabConsole";
import Spinner from "./Spinner";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import { useModelScope } from "../lib/useModelScope";
import { configFromRecord, configToRecord } from "./RuleConfigPanel";
import { formatRuleLabel } from "../lib/ruleDisplay";
import { formatRuleTestEvents } from "../lib/rule-lab-console";

type SavedRule = {
  id: string;
  name: string;
  mode: "rule" | "script";
  config?: Record<string, unknown>;
  source_path?: string;
};

type Props = {
  rules: SavedRule[];
  disabled?: boolean;
};

function clampInt(raw: string, fallback: number, min: number, max: number): number {
  const n = Number.parseInt(raw.trim(), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

export default function FddRuleTestPanel({ rules, disabled }: Props) {
  const activeSiteId = useActiveSiteId();
  const [brickClass, setBrickClass] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [testLimit, setTestLimit] = useState("120");
  const [lookbackHours, setLookbackHours] = useState("24");
  const [testSensorKey, setTestSensorKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [consoleText, setConsoleText] = useState("");
  const scope = useModelScope(activeSiteId, brickClass);

  useEffect(() => {
    if (!ruleId && rules[0]?.id) setRuleId(rules[0].id);
  }, [rules, ruleId]);

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
  }, [scope.equipmentId, scope.sensors, testSensorKey]);

  const activeRule = rules.find((r) => r.id === ruleId);
  const activeSensor = scope.sensors.find((s) => s.point_id === testSensorKey);

  const loadRuleSource = useCallback(async (id: string) => {
    const res = await apiFetch<{ code: string }>(`/api/rules/saved/${id}/source`);
    return res.code || "";
  }, []);

  async function runTest() {
    if (!ruleId || !activeRule) {
      setConsoleText("Select a saved rule to test.");
      return;
    }
    if (activeRule.mode !== "rule") {
      setConsoleText("Only Arrow rule mode can be tested here. Use Rule Lab for script-mode analytics.");
      return;
    }
    if (!testSensorKey) {
      setConsoleText("Pick site, device, and sensor below.");
      return;
    }
    setBusy(true);
    setConsoleText("");
    try {
      const code = await loadRuleSource(ruleId);
      const lookback = clampInt(lookbackHours, 24, 1, 168);
      const limit = clampInt(testLimit, 120, 1, 10_000);
      const res = await apiFetch<{
        rows: number;
        flagged: number;
        data_source?: string;
        value_column?: string;
        scope_warning?: string;
        events: { type: string; text?: string }[];
        trace?: string;
        error?: string;
        ms?: number;
      }>("/api/playground/test-rule", {
        method: "POST",
        body: JSON.stringify({
          code,
          config: configFromRecord(configToRecord((activeRule.config || {}) as Record<string, unknown>)),
          site_id: scope.siteId || undefined,
          equipment_id: scope.equipmentId || undefined,
          point_keys: [testSensorKey],
          lookback_hours: lookback,
          limit,
          chunk_hours: 0,
        }),
      });
      const header = [
        `>>> Test — ${formatRuleLabel(activeRule.name)}`,
        activeSensor ? `sensor: ${activeSensor.label} (${activeSensor.timeseries_column})` : "",
        res.value_column ? `feather column: ${res.value_column}` : "",
        `rows=${res.rows} flagged=${res.flagged} · ${res.data_source} (${res.ms ?? 0} ms)`,
        res.scope_warning ? `⚠ ${res.scope_warning}` : "",
      ]
        .filter(Boolean)
        .join("\n");
      setConsoleText([header, formatRuleTestEvents(res.events || [], { maxLines: 28 }), res.trace || res.error || ""]
        .filter(Boolean)
        .join("\n\n"));
    } catch (e) {
      setConsoleText(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  const consoleLines = useMemo(() => consoleTextToLines(consoleText), [consoleText]);

  return (
    <section className="panel fdd-rule-test-panel">
      <h3 className="panel-title">Test rule against one sensor</h3>
      <p className="muted">
        Run a saved rule against live feather data for one BACnet point. Edit rule Python on{" "}
        <a href="/rule-lab">Rule Lab</a>.
      </p>
      <div className="form-grid">
        <div className="field form-grid-span">
          <label className="field-label" htmlFor="fdd-test-rule">
            Rule
          </label>
          <select id="fdd-test-rule" value={ruleId} onChange={(e) => setRuleId(e.target.value)} disabled={disabled}>
            {rules.map((r) => (
              <option key={r.id} value={r.id}>
                {formatRuleLabel(r.name)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="fdd-test-brick">
            BRICK class filter
          </label>
          <input
            id="fdd-test-brick"
            value={brickClass}
            onChange={(e) => setBrickClass(e.target.value)}
            placeholder="optional"
            disabled={disabled}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="fdd-test-limit">
            Test rows
          </label>
          <input id="fdd-test-limit" value={testLimit} onChange={(e) => setTestLimit(e.target.value)} disabled={disabled} />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="fdd-test-lookback">
            Lookback (h)
          </label>
          <input
            id="fdd-test-lookback"
            value={lookbackHours}
            onChange={(e) => setLookbackHours(e.target.value)}
            disabled={disabled}
          />
        </div>
      </div>
      {scope.loading ? <Spinner label="Loading model scope…" /> : null}
      {scope.error ? <p className="error">{scope.error}</p> : null}
      <div className="form-row model-scope-row">
        <ModelScopePicker
          idPrefix="fdd-test"
          sites={scope.sites}
          siteId={scope.siteId}
          onSiteChange={scope.setSiteId}
          equipment={scope.equipment}
          equipmentId={scope.equipmentId}
          onEquipmentChange={scope.setEquipmentId}
          sensors={scope.sensors}
          sensorPointId={testSensorKey}
          onSensorChange={setTestSensorKey}
          disabled={scope.loading || disabled}
          queryEngine={scope.queryEngine}
        />
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
      <div className="toolbar">
        <button type="button" disabled={busy || disabled} onClick={() => void runTest()}>
          {busy ? "Testing…" : "Test rule"}
        </button>
      </div>
      <RuleLabConsole lines={consoleLines} placeholder="Test output appears here." />
    </section>
  );
}
