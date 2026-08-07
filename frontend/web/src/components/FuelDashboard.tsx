import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FUEL_QUERY_VERSIONS,
  listFuelCampuses,
  postFuelAnalytics,
  type FuelAnalyticsEnvelope,
  type FuelCampusMeta,
  type FuelQueryVersion,
} from "../api/fuelApi";
import {
  demandHeatmap,
  demandPeakDualAxis,
  intensityHeatmapForFuel,
  monthlyLines,
  peakVsCoolSeason,
  rankedSiteEui,
  rolling12Eui,
  stackedFuel,
  summaryPeerBars,
  summaryPeerBullet,
  weatherResidualBars,
  weatherScatter,
} from "../api/fuelCharts";
import {
  DataTable,
  InlineAlert,
  Metric,
  Select,
  Tabs,
} from "./widgets";
import { PlotlyHost } from "./widgets/PlotlyHost";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const TAB_IDS = {
  overview: "portfolio-overview",
  monthly: "monthly-utility",
  weather: "weather-baseline",
  demand: "demand-peak",
  quality: "data-quality",
} as const;

type FuelBundle = Partial<Record<FuelQueryVersion, FuelAnalyticsEnvelope>>;

function campusLabel(c: FuelCampusMeta): string {
  const id = c.campus_id || "unknown";
  return c.label && c.label !== id ? `${c.label} (${id})` : id;
}

/** Derive cool-season (May–Sep) mean OAT by year from weather points when present. */
function coolSeasonFromWeather(
  points: Array<Record<string, unknown>>,
): Record<string, number> {
  const buckets = new Map<string, number[]>();
  for (const p of points) {
    const month = String(p.month ?? "");
    const mon = Number(month.slice(5, 7));
    const year = month.slice(0, 4);
    if (!/^\d{4}$/.test(year) || !(mon >= 5 && mon <= 9)) continue;
    const oat = Number(p.oat ?? p.mean_oat_f ?? p.x);
    if (!Number.isFinite(oat)) continue;
    const list = buckets.get(year) ?? [];
    list.push(oat);
    buckets.set(year, list);
  }
  const out: Record<string, number> = {};
  for (const [y, vals] of buckets) {
    if (!vals.length) continue;
    out[y] = vals.reduce((a, b) => a + b, 0) / vals.length;
  }
  return out;
}

export function FuelDashboard() {
  const [campuses, setCampuses] = useState<FuelCampusMeta[]>([]);
  const [campusId, setCampusId] = useState("");
  const [tab, setTab] = useState<string>(TAB_IDS.overview);
  const [bundle, setBundle] = useState<FuelBundle>({});
  const [loadingCampuses, setLoadingCampuses] = useState(true);
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const refreshCampuses = useCallback(async () => {
    setLoadingCampuses(true);
    setError(null);
    try {
      const res = await listFuelCampuses();
      const list = Array.isArray(res.campuses) ? res.campuses : [];
      setCampuses(list.filter((c) => c.campus_id && !c.error));
      setCampusId((prev) => {
        if (prev && list.some((c) => c.campus_id === prev)) return prev;
        const active = res.active?.campus_id;
        if (active && list.some((c) => c.campus_id === active)) return active;
        return list[0]?.campus_id ?? "";
      });
    } catch (err) {
      setCampuses([]);
      setCampusId("");
      setError(formatErr(err));
    } finally {
      setLoadingCampuses(false);
    }
  }, []);

  useEffect(() => {
    void refreshCampuses();
  }, [refreshCampuses]);

  useEffect(() => {
    if (!campusId) {
      setBundle({});
      setWarnings([]);
      return;
    }
    let cancelled = false;
    setLoadingAnalytics(true);
    setError(null);
    void (async () => {
      try {
        const results = await Promise.all(
          FUEL_QUERY_VERSIONS.map(async (qv) => {
            const env = await postFuelAnalytics({
              query_version: qv,
              campus_id: campusId,
              allocation: "area_weighted",
            });
            return [qv, env] as const;
          }),
        );
        if (cancelled) return;
        const next: FuelBundle = {};
        const warns: string[] = [];
        for (const [qv, env] of results) {
          next[qv] = env;
          for (const w of env.warnings ?? []) {
            if (w) warns.push(`${qv}: ${w}`);
          }
        }
        setBundle(next);
        setWarnings(warns);
      } catch (err) {
        if (!cancelled) {
          setBundle({});
          setError(formatErr(err));
        }
      } finally {
        if (!cancelled) setLoadingAnalytics(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [campusId]);

  const summary = bundle["fuel-summary-v1"];
  const monthly = bundle["fuel-monthly-v1"];
  const stacked = bundle["fuel-stacked-v1"];
  const intensity = bundle["fuel-intensity-v1"];
  const demand = bundle["fuel-demand-v1"];
  const quality = bundle["fuel-quality-v1"];
  const weather = bundle["fuel-weather-v1"];

  const campusSummary = summary?.summary?.campus as
    | Record<string, unknown>
    | undefined;
  const floorArea =
    Number(campusSummary?.floor_area_ft2 ?? campusSummary?.area_ft2) ||
    Number(
      campuses.find((c) => c.campus_id === campusId)?.total_area_ft2,
    ) ||
    null;

  const coolSeason = useMemo(
    () => coolSeasonFromWeather(weather?.points ?? weather?.rows ?? []),
    [weather],
  );

  const bulletFig = useMemo(
    () => summaryPeerBullet(summary?.rows ?? []),
    [summary],
  );
  const summaryFig = useMemo(
    () => summaryPeerBars(summary?.rows ?? []),
    [summary],
  );
  const rankedFig = useMemo(
    () => rankedSiteEui(summary?.rows ?? []),
    [summary],
  );
  const elecHeatFig = useMemo(
    () => intensityHeatmapForFuel(intensity?.rows ?? [], "electric"),
    [intensity],
  );
  const gasHeatFig = useMemo(
    () => intensityHeatmapForFuel(intensity?.rows ?? [], "gas"),
    [intensity],
  );
  const stackedFig = useMemo(
    () => stackedFuel(stacked?.rows ?? []),
    [stacked],
  );
  const monthlyFig = useMemo(
    () => monthlyLines(monthly?.rows ?? []),
    [monthly],
  );
  const roll12Fig = useMemo(
    () =>
      rolling12Eui(
        stacked?.rows?.length ? stacked.rows : (monthly?.rows ?? []),
        floorArea,
      ),
    [stacked, monthly, floorArea],
  );
  const demandFig = useMemo(
    () => demandHeatmap(demand?.rows ?? []),
    [demand],
  );
  const demandPeakFig = useMemo(
    () => demandPeakDualAxis(demand?.rows ?? [], coolSeason),
    [demand, coolSeason],
  );
  const peakCoolFig = useMemo(
    () => peakVsCoolSeason(demand?.rows ?? [], coolSeason),
    [demand, coolSeason],
  );
  const weatherFig = useMemo(
    () =>
      weatherScatter(weather?.points ?? weather?.rows ?? [], weather?.fits),
    [weather],
  );
  const residualFigs = useMemo(() => {
    const points = weather?.points ?? weather?.rows ?? [];
    return (weather?.fits ?? [])
      .map((fit) => ({
        fuel: String(fit.fuel ?? ""),
        fig: weatherResidualBars(points, fit),
      }))
      .filter((x) => x.fig);
  }, [weather]);

  const qualityRows = useMemo(
    () =>
      (quality?.rows ?? []).map((r) => ({
        meter_id: String(r.meter_id ?? ""),
        fuel: String(r.fuel ?? ""),
        n_months: String(r.n_months ?? ""),
        completeness_pct: String(r.completeness_pct ?? ""),
        cost_coverage_pct: String(
          typeof r.cost_coverage_pct === "number"
            ? Math.round(r.cost_coverage_pct * 10) / 10
            : (r.cost_coverage_pct ?? ""),
        ),
        demand_coverage_pct: String(
          typeof r.demand_coverage_pct === "number"
            ? Math.round(Number(r.demand_coverage_pct) * 10) / 10
            : (r.demand_coverage_pct ?? ""),
        ),
        missing_months: Array.isArray(r.missing_months)
          ? (r.missing_months as unknown[]).join(", ")
          : String(r.missing_months ?? ""),
      })),
    [quality],
  );

  const fitRows = useMemo(
    () =>
      (weather?.fits ?? []).map((f) => ({
        fuel: String(f.fuel ?? ""),
        x: String(f.x ?? ""),
        n_months: String(f.n_months ?? ""),
        slope: String(f.slope ?? ""),
        intercept: String(f.intercept ?? ""),
        r2: String(f.r2 ?? ""),
      })),
    [weather],
  );

  if (!loadingCampuses && campuses.length === 0) {
    return (
      <div data-testid="fuel-dashboard" className="page-stack">
        <InlineAlert id="fuel-empty" variant="info" testId="fuel-upload-prompt">
          No fuel campuses imported yet. Use the Uploads tab to import a fuel
          campus ZIP (campus.json + bill CSVs), then return here.
        </InlineAlert>
        {error ? (
          <InlineAlert id="fuel-error" variant="danger">
            {error}
          </InlineAlert>
        ) : null}
      </div>
    );
  }

  return (
    <div data-testid="fuel-dashboard" className="page-stack">
      <Select
        id="fuel-campus"
        label="Fuel campus"
        description="Imported via POST /api/fuel/campus/import"
        value={campusId}
        options={[
          { value: "", label: "— select campus —" },
          ...campuses.map((c) => ({
            value: c.campus_id,
            label: campusLabel(c),
          })),
        ]}
        onChange={setCampusId}
        loading={loadingCampuses}
        disabled={loadingCampuses}
        testId="fuel-campus-select"
      />

      {error ? (
        <InlineAlert id="fuel-error" variant="danger">
          {error}
        </InlineAlert>
      ) : null}
      {warnings.length > 0 ? (
        <InlineAlert id="fuel-warnings" variant="warning" testId="fuel-warnings">
          {warnings.slice(0, 6).join(" · ")}
          {warnings.length > 6 ? ` (+${warnings.length - 6} more)` : ""}
        </InlineAlert>
      ) : null}

      <Tabs
        id="fuel-tabs"
        label="Fuel analytics"
        activeTabId={tab}
        onChange={setTab}
        testId="fuel-tabs"
        loading={loadingAnalytics}
        tabs={[
          {
            id: TAB_IDS.overview,
            label: "Portfolio Overview",
            content: (
              <div data-testid="fuel-tab-portfolio-overview" className="page-stack">
                <div className="oracle-sidebar__btn-row">
                  <Metric
                    id="fuel-kpi-buildings"
                    label="Buildings"
                    value={String(
                      summary?.coverage?.building_count ??
                        summary?.rows?.length ??
                        "—",
                    )}
                    loading={loadingAnalytics}
                    testId="fuel-kpi-buildings"
                  />
                  <Metric
                    id="fuel-kpi-meters"
                    label="Meters"
                    value={String(summary?.coverage?.meter_count ?? "—")}
                    loading={loadingAnalytics}
                    testId="fuel-kpi-meters"
                  />
                  <Metric
                    id="fuel-kpi-eui"
                    label="Campus site EUI"
                    value={
                      campusSummary?.site_eui_kbtu_ft2 != null
                        ? String(campusSummary.site_eui_kbtu_ft2)
                        : "—"
                    }
                    description="kBtu/ft²·yr"
                    loading={loadingAnalytics}
                    testId="fuel-kpi-eui"
                  />
                </div>
                <PlotlyHost
                  id="fuel-summary-bullet"
                  label="Site EUI vs peer band (p20–p80)"
                  figure={bulletFig ?? summaryFig}
                  loading={loadingAnalytics}
                  height={420}
                  testId="fuel-chart-summary"
                />
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "1rem",
                  }}
                  data-testid="fuel-intensity-pair"
                >
                  <PlotlyHost
                    id="fuel-intensity-elec"
                    label="Elec intensity"
                    figure={elecHeatFig}
                    loading={loadingAnalytics}
                    height={360}
                    testId="fuel-chart-intensity-elec"
                  />
                  <PlotlyHost
                    id="fuel-intensity-gas"
                    label="Gas intensity"
                    figure={gasHeatFig}
                    loading={loadingAnalytics}
                    height={360}
                    testId="fuel-chart-intensity-gas"
                  />
                </div>
                <PlotlyHost
                  id="fuel-ranked-eui"
                  label="Ranked site EUI"
                  figure={rankedFig}
                  loading={loadingAnalytics}
                  height={360}
                  testId="fuel-chart-ranked"
                />
                {summary?.rows?.length ? (
                  <DataTable
                    id="fuel-summary-table"
                    label="Building summary"
                    columns={[
                      { key: "building_id", header: "Building" },
                      { key: "site_eui", header: "Site EUI" },
                      { key: "peer_p50", header: "Peer p50" },
                      { key: "band", header: "Band" },
                    ]}
                    rows={(summary.rows ?? []).map((r) => {
                      const peer =
                        r.peer && typeof r.peer === "object"
                          ? (r.peer as Record<string, unknown>)
                          : {};
                      return {
                        building_id: String(r.building_id ?? ""),
                        site_eui: String(
                          r.site_eui_kbtu_ft2 ?? r.site_eui ?? "",
                        ),
                        peer_p50: String(peer.p50 ?? r.peer_p50 ?? ""),
                        band: String(peer.band ?? ""),
                      };
                    })}
                    testId="fuel-summary-table"
                  />
                ) : null}
              </div>
            ),
          },
          {
            id: TAB_IDS.monthly,
            label: "Monthly Utility Analytics",
            content: (
              <div data-testid="fuel-tab-monthly-utility" className="page-stack">
                <PlotlyHost
                  id="fuel-stacked"
                  label="Stacked fuel (kBtu)"
                  figure={stackedFig}
                  loading={loadingAnalytics}
                  height={420}
                  testId="fuel-chart-stacked"
                />
                <PlotlyHost
                  id="fuel-monthly"
                  label="Monthly by meter"
                  figure={monthlyFig}
                  loading={loadingAnalytics}
                  height={400}
                  testId="fuel-chart-monthly"
                />
                <PlotlyHost
                  id="fuel-roll12"
                  label="Rolling 12-month site EUI"
                  figure={roll12Fig}
                  loading={loadingAnalytics}
                  height={320}
                  testId="fuel-chart-roll12"
                />
              </div>
            ),
          },
          {
            id: TAB_IDS.weather,
            label: "Weather & Baseline",
            content: (
              <div data-testid="fuel-tab-weather-baseline" className="page-stack">
                <PlotlyHost
                  id="fuel-weather"
                  label="Weather vs usage"
                  figure={weatherFig}
                  loading={loadingAnalytics}
                  height={420}
                  testId="fuel-chart-weather"
                />
                {residualFigs.map(({ fuel, fig }) => (
                  <PlotlyHost
                    key={fuel}
                    id={`fuel-resid-${fuel}`}
                    label={`${fuel} residuals`}
                    figure={fig}
                    loading={loadingAnalytics}
                    height={280}
                    testId={`fuel-chart-resid-${fuel}`}
                  />
                ))}
                {fitRows.length > 0 ? (
                  <DataTable
                    id="fuel-fits"
                    label="OLS fits"
                    columns={[
                      { key: "fuel", header: "Fuel" },
                      { key: "x", header: "X" },
                      { key: "n_months", header: "N" },
                      { key: "slope", header: "Slope" },
                      { key: "intercept", header: "Intercept" },
                      { key: "r2", header: "R²" },
                    ]}
                    rows={fitRows}
                    testId="fuel-fits-table"
                  />
                ) : (
                  <p data-testid="fuel-fits-empty">
                    No OLS fits yet (need ≥6 aligned months per fuel).
                  </p>
                )}
              </div>
            ),
          },
          {
            id: TAB_IDS.demand,
            label: "Demand & Peak",
            content: (
              <div data-testid="fuel-tab-demand-peak" className="page-stack">
                <PlotlyHost
                  id="fuel-demand"
                  label="Peak demand heatmap"
                  figure={demandFig}
                  loading={loadingAnalytics}
                  height={400}
                  testId="fuel-chart-demand"
                />
                <PlotlyHost
                  id="fuel-demand-peak"
                  label="Peak by year"
                  figure={demandPeakFig}
                  loading={loadingAnalytics}
                  height={380}
                  testId="fuel-chart-demand-peak"
                />
                <PlotlyHost
                  id="fuel-peak-cool"
                  label="Peak vs cool-season"
                  figure={peakCoolFig}
                  loading={loadingAnalytics}
                  height={360}
                  testId="fuel-chart-peak-cool"
                />
              </div>
            ),
          },
          {
            id: TAB_IDS.quality,
            label: "Data Quality",
            content: (
              <div data-testid="fuel-tab-data-quality" className="page-stack">
                <DataTable
                  id="fuel-quality"
                  label="Meter completeness"
                  columns={[
                    { key: "meter_id", header: "Meter" },
                    { key: "fuel", header: "Fuel" },
                    { key: "n_months", header: "Months" },
                    { key: "completeness_pct", header: "Completeness %" },
                    { key: "cost_coverage_pct", header: "Cost %" },
                    { key: "demand_coverage_pct", header: "Demand %" },
                    { key: "missing_months", header: "Missing" },
                  ]}
                  rows={qualityRows}
                  loading={loadingAnalytics}
                  testId="fuel-quality-table"
                />
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
