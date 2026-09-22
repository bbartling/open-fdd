import { useEffect, useMemo, useState } from "react";
import { DataTable, InlineAlert } from "./widgets";
import { postSqlAnomaly } from "../api/analyticsApi";
import { naturalCompare } from "../lib/naturalSort";

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

function fmtTs(v: unknown): string {
  if (v == null || v === "") return "—";
  const s = String(v);
  return s.length > 19 ? s.slice(0, 19).replace("T", " ") : s;
}

/** Overview tabulated SQL anomaly screening (rolling Z-score; no Plotly). */
export function SqlAnomalySection({
  buildingId,
  refreshToken,
}: {
  buildingId: string;
  refreshToken: number;
}) {
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!buildingId) {
      setRows([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setNote(null);
    void (async () => {
      try {
        const env = await postSqlAnomaly({
          building_id: buildingId,
          query_version: "sql-anomaly-v1",
          series: {
            window_rows: 24,
            z_threshold: 3,
            method: "zscore",
            transition_events: true,
          },
        });
        if (cancelled) return;
        const warnings = env.warnings ?? [];
        if (warnings.some((w) => w.includes("disabled"))) {
          setNote(
            "SQL anomaly screening is disabled on this central (OPENFDD_SQL_ANOMALY_SCREENING=0).",
          );
          setRows([]);
          return;
        }
        if (warnings.some((w) => w.includes("no mapped"))) {
          setNote(
            "No mapped SAT/OAT/zone sensor columns in historian — import package roles first.",
          );
          setRows([]);
          return;
        }
        const sorted = [...(env.rows ?? [])].sort((a, b) => {
          const ah = Number(a.anomaly_hours) || 0;
          const bh = Number(b.anomaly_hours) || 0;
          if (bh !== ah) return bh - ah;
          const as = Number(a.score) || 0;
          const bs = Number(b.score) || 0;
          if (bs !== as) return bs - as;
          return naturalCompare(String(a.equipment_id), String(b.equipment_id));
        });
        setRows(sorted);
        if (!sorted.length) {
          setNote("No rolling Z-score anomalies above threshold in this window.");
        }
      } catch (e) {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : String(e));
          setRows([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [buildingId, refreshToken]);

  const tableRows = useMemo(
    () =>
      rows.map((r) => ({
        equipment_id: String(r.equipment_id ?? ""),
        role: String(r.role ?? r.metric ?? ""),
        method: String(r.method ?? "zscore"),
        score: fmtNum(r.score),
        threshold: fmtNum(r.threshold, 1),
        anomaly_hours: fmtNum(r.anomaly_hours, 1),
        anomaly_events: fmtNum(r.anomaly_events, 0),
        last_at: fmtTs(r.last_at),
      })),
    [rows],
  );

  return (
    <section className="overview-section" data-testid="overview-sql-anomaly">
      <h3>Anomaly screening (SQL)</h3>
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
        <InlineAlert id="overview-sql-anomaly-err" variant="danger">
          {err}
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
          label="SQL anomaly overview"
          columns={[
            { key: "equipment_id", header: "equipment" },
            { key: "role", header: "role / metric" },
            { key: "method", header: "method" },
            { key: "score", header: "max |z|" },
            { key: "threshold", header: "threshold" },
            { key: "anomaly_hours", header: "anomaly h" },
            { key: "anomaly_events", header: "events" },
            { key: "last_at", header: "last_at" },
          ]}
          rows={tableRows}
          testId="overview-sql-anomaly-table"
        />
      ) : null}
    </section>
  );
}
