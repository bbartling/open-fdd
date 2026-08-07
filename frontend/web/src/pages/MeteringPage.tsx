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
import { PlotlyHost } from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  monthlySumClient,
  postMetering,
  postRcxPreset,
  type AnalyticsEnvelope,
  type MeterRow,
  type MonthlySumRow,
} from "../api/analyticsApi";
import { meteringCharts } from "../api/vibeCharts";
import type { PlotlyFigure } from "../api/plotDataset";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

type SumTableRow = {
  period: string;
  kwh: string;
  n_rows: string;
  meter_id: string;
};

const METER_PRESETS = [
  {
    id: "meter_elec_cdd",
    label: "Electric × CDD (RCx metering preset)",
  },
  {
    id: "meter_gas_hdd",
    label: "Gas × HDD (RCx metering preset)",
  },
] as const;

export function MeteringPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [seriesJson, setSeriesJson] = useState(
    () => JSON.stringify({ rows: SAMPLE_METER_ROWS_DEFAULT }, null, 2),
  );
  const [presetId, setPresetId] = useState<string>(METER_PRESETS[0].id);
  const [envelope, setEnvelope] = useState<AnalyticsEnvelope | null>(null);
  const [clientSums, setClientSums] = useState<MonthlySumRow[]>([]);
  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
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

      // Build Plotly from monthly sums (bars) — vibe19 meteringCharts shape.
      const points = (env.rows?.length ? env.rows : monthlySumClient(rows)).map(
        (r) => ({
          equipment_id: String(r.meter_id ?? (buildingId || "meter")),
          month: String(r.period ?? ""),
          energy: Number(r.kwh),
          value_f: Number(r.kwh),
          degree_days: null,
        }),
      );
      setFigure(
        meteringCharts(points, {
          title: "Monthly energy (inline series)",
          ddLabel: "DD",
        }),
      );
    } catch (err) {
      setEnvelope(null);
      setFigure(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, seriesJson]);

  const runMeterPreset = useCallback(async () => {
    if (!buildingId) {
      setError("Select a building for RCx metering presets");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const env = await postRcxPreset({
        building_id: buildingId,
        max_points: 8000,
        series: { preset_id: presetId },
      });
      setEnvelope(env);
      setClientSums([]);
      const title = String(
        env.coverage?.title ??
          METER_PRESETS.find((p) => p.id === presetId)?.label ??
          presetId,
      );
      const ddLabel =
        String(env.coverage?.meter_kind ?? "") === "gas" ||
        presetId.includes("gas")
          ? "HDD"
          : "CDD";
      const points = env.points ?? [];
      if (!points.length) {
        setFigure(null);
        if (env.warnings?.length) setError(env.warnings[0] ?? "No points");
        return;
      }
      setFigure(meteringCharts(points, { title, ddLabel }));
    } catch (err) {
      setEnvelope(null);
      setFigure(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, presetId]);

  const tableRows: SumTableRow[] = useMemo(() => {
    if (envelope?.points?.length) {
      return envelope.points.slice(0, 120).map((r) => ({
        period: String(r.month ?? r.period ?? ""),
        kwh: String(r.energy ?? r.value_f ?? r.kwh ?? ""),
        n_rows: String(r.n_rows ?? ""),
        meter_id: String(r.equipment_id ?? r.meter_id ?? ""),
      }));
    }
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
      caption="Monthly energy + degree-day charts via metering analytics / RCx presets"
      activeSectionId="metering"
    >
      <div className="page-stack" data-testid="metering-page">
        <InlineAlert id="metering-scope" variant="info">
          Prefer Plotly from RCx metering presets (
          <code>meter_elec_cdd</code> / <code>meter_gas_hdd</code>) or run the
          inline monthly kWh sum. JSON remains an advanced input, not the
          primary UX.
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
          <Select
            id="metering-preset"
            label="Metering preset"
            value={presetId}
            options={METER_PRESETS.map((p) => ({
              value: p.id,
              label: p.label,
            }))}
            onChange={setPresetId}
            testId="metering-preset"
          />
        </div>

        <div className="form-row" style={{ gap: "0.5rem", display: "flex" }}>
          <Button
            id="metering-preset-run"
            label={loading ? "Running…" : "Run metering preset"}
            onClick={() => void runMeterPreset()}
            disabled={loading || !buildingId}
            testId="metering-preset-run"
          />
          <Button
            id="metering-run"
            label={loading ? "Running…" : "Run inline monthly sum"}
            variant="secondary"
            onClick={() => void runMetering()}
            disabled={loading}
            testId="metering-run"
          />
          <Link to="/rcx">RCx Plots</Link>
        </div>

        <details data-testid="metering-series-advanced">
          <summary>Advanced: inline series JSON</summary>
          <label htmlFor="metering-series">
            Series JSON
            <textarea
              id="metering-series"
              data-testid="metering-series"
              rows={8}
              value={seriesJson}
              onChange={(e) => setSeriesJson(e.target.value)}
              style={{ width: "100%", fontFamily: "monospace" }}
            />
          </label>
        </details>

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

        <PlotlyHost
          id="metering-plot"
          label="Metering chart"
          figure={figure}
          loading={loading}
          height={420}
          testId="metering-plot"
        />

        <DataTable
          id="metering-table"
          label="Monthly energy"
          columns={[
            { key: "period", header: "Period" },
            { key: "kwh", header: "kWh / energy" },
            { key: "n_rows", header: "n_rows" },
            { key: "meter_id", header: "meter / equipment" },
          ]}
          rows={tableRows}
          testId="metering-table"
        />
      </div>
    </AppShell>
  );
}

const SAMPLE_METER_ROWS_DEFAULT = [
  { period: "2024-01", kwh: 100.25, meter_id: "M1" },
  { period: "2024-01", kwh: 50.25, meter_id: "M1" },
  { period: "2024-02", kwh: 200, meter_id: "M1" },
  { period: "2024-03", kwh: 175.25, meter_id: "M1" },
];
