import { useEffect, useMemo, useState } from "react";
import { DataTable, InlineAlert } from "./widgets";
import { postSqlAnomaly } from "../api/analyticsApi";
import {
  overviewQueryRequestsRefresh,
  useOverviewQueryEpoch,
} from "../session/overviewQueryPolicy";
import {
  SQL_ANOMALY_QUERY_VERSION,
  anomalyEdgeNote,
  anomalyEmptyNote,
  formatAnomalyNumber,
  formatAnomalyTimestamp,
  parseAnomalyEnvelope,
  parseWindowRows,
  parseZThreshold,
  sortAnomalyEvents,
  type AnomalyEvent,
} from "./sqlAnomaly";

const CONTROL_NOTE =
  "Window is a whole number from 3 to 168. Threshold is a positive number up to 100.";

/** Overview event table for rolling prior-window z-score (no Plotly). */
export function SqlAnomalySection({
  buildingId,
  refreshToken,
}: {
  buildingId: string;
  refreshToken: number;
}) {
  const [windowText, setWindowText] = useState("24");
  const [thresholdText, setThresholdText] = useState("3");
  const [edgesOnly, setEdgesOnly] = useState(false);
  const [rows, setRows] = useState<AnomalyEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [edgeNote, setEdgeNote] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [scopeId, setScopeId] = useState(buildingId);
  const queryEpoch = useOverviewQueryEpoch(buildingId, "sql-anomaly");
  if (scopeId !== buildingId) {
    setScopeId(buildingId);
    setRows([]);
    setErr(null);
    setNote(null);
    setEdgeNote(null);
    setTruncated(false);
    setLoading(true);
  }
  const windowRows = parseWindowRows(windowText);
  const threshold = parseZThreshold(thresholdText);

  useEffect(() => {
    if (!buildingId) {
      setRows([]);
      setErr(null);
      setNote(null);
      setEdgeNote(null);
      setTruncated(false);
      setLoading(false);
      return;
    }
    if (windowRows == null || threshold == null) {
      setRows([]);
      setErr(null);
      setEdgeNote(null);
      setTruncated(false);
      setNote(CONTROL_NOTE);
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setErr(null);
    setNote(null);
    setEdgeNote(null);
    void (async () => {
      try {
        const refresh = overviewQueryRequestsRefresh(buildingId, "sql-anomaly");
        const env = await postSqlAnomaly(
          {
            building_id: buildingId,
            query_version: SQL_ANOMALY_QUERY_VERSION,
            series: {
              window_rows: windowRows,
              z_threshold: threshold,
              method: "zscore",
              transition_events: edgesOnly,
            },
            ...(refresh ? { refresh: true } : {}),
          },
          { signal: ctrl.signal },
        );
        if (ctrl.signal.aborted) return;
        const parsed = parseAnomalyEnvelope(env);
        setRows(sortAnomalyEvents(parsed.rows));
        setNote(anomalyEmptyNote(parsed));
        setEdgeNote(anomalyEdgeNote(parsed));
        setTruncated(parsed.coverage.truncated);
      } catch (error) {
        if (ctrl.signal.aborted) return;
        setErr(error instanceof Error ? error.message : String(error));
        setRows([]);
        setNote(null);
        setEdgeNote(null);
        setTruncated(false);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [buildingId, edgesOnly, queryEpoch, refreshToken, threshold, windowRows]);

  const tableRows = useMemo(
    () =>
      rows.map((row) => ({
        row_key: row.row_key,
        equipment_id: row.equipment_id,
        role: row.role,
        ts: formatAnomalyTimestamp(row.ts),
        val: formatAnomalyNumber(row.val),
        avg_val: formatAnomalyNumber(row.avg_val),
        stddev_val: formatAnomalyNumber(row.stddev_val),
        z_abs: formatAnomalyNumber(row.z_abs),
        threshold: formatAnomalyNumber(row.threshold),
        anomaly_flag: row.anomaly_flag,
        transition: row.transition ? "true" : "false",
      })),
    [rows],
  );

  return (
    <section className="overview-section" data-testid="overview-sql-anomaly">
      <h3>Anomaly screening (SQL)</h3>
      <div className="form-row overview-anomaly-controls">
        <label htmlFor="overview-sql-anomaly-window">
          Window
          <input
            id="overview-sql-anomaly-window"
            data-testid="overview-sql-anomaly-window"
            type="number"
            min={3}
            max={168}
            step={1}
            value={windowText}
            onChange={(event) => setWindowText(event.target.value)}
          />
        </label>
        <label htmlFor="overview-sql-anomaly-threshold">
          Threshold
          <input
            id="overview-sql-anomaly-threshold"
            data-testid="overview-sql-anomaly-threshold"
            type="number"
            min={0.001}
            max={100}
            step="any"
            value={thresholdText}
            onChange={(event) => setThresholdText(event.target.value)}
          />
        </label>
        <label htmlFor="overview-sql-anomaly-transitions">
          <input
            id="overview-sql-anomaly-transitions"
            data-testid="overview-sql-anomaly-transitions"
            type="checkbox"
            checked={edgesOnly}
            onChange={(event) => setEdgesOnly(event.target.checked)}
          />
          Rising edges only
        </label>
      </div>
      {loading ? (
        <InlineAlert
          id="overview-sql-anomaly-loading"
          variant="info"
          testId="overview-sql-anomaly-loading"
        >
          Loading…
        </InlineAlert>
      ) : null}
      {err ? (
        <InlineAlert
          id="overview-sql-anomaly-err"
          variant="danger"
          testId="overview-sql-anomaly-err"
        >
          {err}
        </InlineAlert>
      ) : null}
      {edgeNote && !err ? (
        <InlineAlert
          id="overview-sql-anomaly-edges"
          variant="info"
          testId="overview-sql-anomaly-edges"
        >
          {edgeNote}
        </InlineAlert>
      ) : null}
      {truncated && !err ? (
        <InlineAlert
          id="overview-sql-anomaly-truncated"
          variant="info"
          testId="overview-sql-anomaly-truncated"
        >
          The event table stops at 2000 rows. Flagged-sample coverage still counts the rest.
        </InlineAlert>
      ) : null}
      {note && !err ? (
        <InlineAlert
          id="overview-sql-anomaly-empty"
          variant="info"
          testId="overview-sql-anomaly-empty"
        >
          {note}
        </InlineAlert>
      ) : null}
      {tableRows.length > 0 ? (
        <DataTable
          id="sql-anomaly-overview"
          label="SQL anomaly events"
          columns={[
            { key: "equipment_id", header: "equipment" },
            { key: "role", header: "role" },
            { key: "ts", header: "time (UTC)" },
            { key: "val", header: "value" },
            { key: "avg_val", header: "baseline" },
            { key: "stddev_val", header: "stddev" },
            { key: "z_abs", header: "|z|" },
            { key: "threshold", header: "threshold" },
            { key: "anomaly_flag", header: "flag" },
            { key: "transition", header: "edge" },
          ]}
          rows={tableRows}
          testId="overview-sql-anomaly-table"
        />
      ) : null}
    </section>
  );
}
