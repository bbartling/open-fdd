import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  InlineAlert,
  Metric,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  monthlySumClient,
  postMetering,
  postRcxAhu,
  SAMPLE_METER_ROWS,
  type AnalyticsEnvelope,
  type MeterRow,
  type MonthlySumRow,
} from "../api/analyticsApi";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

type SumTableRow = {
  period: string;
  kwh: string;
  n_rows: string;
  meter_id: string;
};

export function MeteringPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [seriesJson, setSeriesJson] = useState(
    () => JSON.stringify({ rows: SAMPLE_METER_ROWS }, null, 2),
  );
  const [envelope, setEnvelope] = useState<AnalyticsEnvelope | null>(null);
  const [clientSums, setClientSums] = useState<MonthlySumRow[]>([]);
  const [rcxEnv, setRcxEnv] = useState<AnalyticsEnvelope | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPackageBuildings()
      .then((b) => {
        if (!cancelled) setBuildings(b);
      })
      .catch(() => {
        if (!cancelled) setBuildings([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runMetering = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let parsed: { rows?: MeterRow[] } | MeterRow[];
      try {
        parsed = JSON.parse(seriesJson) as { rows?: MeterRow[] } | MeterRow[];
      } catch {
        throw new Error("Series JSON is invalid");
      }
      const rows = Array.isArray(parsed)
        ? parsed
        : Array.isArray(parsed.rows)
          ? parsed.rows
          : [];
      if (rows.length === 0) {
        throw new Error("Provide at least one {period,kwh} row");
      }
      setClientSums(monthlySumClient(rows));
      const env = await postMetering({
        building_id: buildingId || undefined,
        series: { rows },
        query_version: "metering-v1",
      });
      setEnvelope(env);
    } catch (err) {
      setEnvelope(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, seriesJson]);

  const runRcxStub = useCallback(async () => {
    setError(null);
    try {
      const env = await postRcxAhu({
        building_id: buildingId || undefined,
        series: {
          points: [
            {
              equipment_id: "AHU_1",
              role: "sat_sp",
              timestamp: "2024-01-01T12:00:00Z",
              value: 55,
            },
            {
              equipment_id: "AHU_1",
              role: "duct_static_sp",
              timestamp: "2024-01-01T12:00:00Z",
              value: 1.2,
            },
          ],
        },
        query_version: "rcx-ahu-v1",
      });
      setRcxEnv(env);
    } catch (err) {
      setRcxEnv(null);
      setError(formatErr(err));
    }
  }, [buildingId]);

  const tableRows: SumTableRow[] = useMemo(() => {
    const src =
      envelope?.rows?.length && envelope.rows.length > 0
        ? envelope.rows
        : clientSums;
    return src.map((r) => ({
      period: String(r.period ?? ""),
      kwh: String(r.kwh ?? ""),
      n_rows: String(r.n_rows ?? ""),
      meter_id: String(r.meter_id ?? ""),
    }));
  }, [envelope, clientSums]);

  const totalKwh =
    (envelope?.coverage?.total_kwh as number | undefined) ??
    clientSums.reduce((a, r) => a + r.kwh, 0);

  const parityOk =
    envelope != null &&
    clientSums.length > 0 &&
    envelope.rows.length === clientSums.length &&
    envelope.rows.every((r, i) => {
      const c = clientSums[i];
      return (
        c &&
        String(r.period) === c.period &&
        Math.abs(Number(r.kwh) - c.kwh) < 1e-6
      );
    });

  return (
    <AppShell
      title="Metering"
      caption="Monthly kWh sum via POST /api/analytics/metering (P1-M5-C)"
      activeSectionId="metering"
    >
      <div className="page-stack" data-testid="metering-page">
        <InlineAlert id="metering-scope" variant="info">
          Inline {"{period,kwh}"} rows drive the Rust monthly sum. Historian path
          returns descriptive counts when series is omitted. RCx AHU stub uses the
          same analytics envelope family.
        </InlineAlert>

        <div className="form-row">
          <Select
            id="metering-building"
            label="Building"
            value={buildingId}
            options={[
              { value: "", label: "— building —" },
              ...buildings.map((b) => ({ value: b, label: b })),
            ]}
            onChange={(v) => setQuery({ siteId: v || undefined }, true)}
            testId="metering-building"
          />
        </div>

        <label htmlFor="metering-series">
          Series JSON
          <textarea
            id="metering-series"
            data-testid="metering-series"
            rows={10}
            value={seriesJson}
            onChange={(e) => setSeriesJson(e.target.value)}
            style={{ width: "100%", fontFamily: "monospace" }}
          />
        </label>

        <div className="form-row" style={{ gap: "0.5rem", display: "flex" }}>
          <Button
            id="metering-run"
            label={loading ? "Running…" : "Run metering"}
            onClick={() => void runMetering()}
            disabled={loading}
            testId="metering-run"
          />
          <Button
            id="metering-rcx"
            label="Run RCx AHU stub"
            variant="secondary"
            onClick={() => void runRcxStub()}
            testId="metering-rcx"
          />
          <Link to="/?section=overview">Overview</Link>
        </div>

        {error && (
          <InlineAlert id="metering-error" variant="danger">
            {error}
          </InlineAlert>
        )}

        <div
          className="metric-row"
          style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}
        >
          <Metric
            id="metering-total"
            label="Total kWh"
            value={Number.isFinite(totalKwh) ? totalKwh.toFixed(2) : "—"}
            testId="metering-total"
          />
          <Metric
            id="metering-periods"
            label="Periods"
            value={String(tableRows.length)}
            testId="metering-periods"
          />
          <Metric
            id="metering-engine"
            label="Engine"
            value={envelope?.engine ?? "—"}
            testId="metering-engine"
          />
          <Metric
            id="metering-parity"
            label="Client↔API parity"
            value={parityOk ? "PASS" : envelope ? "CHECK" : "—"}
            testId="metering-parity"
          />
        </div>

        {envelope?.warnings?.length ? (
          <InlineAlert id="metering-warn" variant="warning">
            {envelope.warnings.join(" · ")}
          </InlineAlert>
        ) : null}

        <DataTable
          id="metering-table"
          label="Monthly kWh sums"
          columns={[
            { key: "period", header: "Period" },
            { key: "kwh", header: "kWh" },
            { key: "n_rows", header: "n_rows" },
            { key: "meter_id", header: "meter_id" },
          ]}
          rows={tableRows}
          testId="metering-table"
        />

        {rcxEnv && (
          <section data-testid="metering-rcx-result">
            <h3>RCx AHU envelope</h3>
            <p>
              query_version={rcxEnv.query_version} · engine={rcxEnv.engine} ·
              rows={rcxEnv.rows.length}
            </p>
            <pre style={{ maxHeight: 200, overflow: "auto" }}>
              {JSON.stringify(rcxEnv.rows, null, 2)}
            </pre>
          </section>
        )}
      </div>
    </AppShell>
  );
}
