import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import { SeriesPreview } from "../components/SeriesPreview";
import { LockedSiteCaption } from "../components/LockedSiteCaption";
import {
  InlineAlert,
  Select,
  Button,
  DataTable,
  Checkbox,
} from "../components/widgets";
import {
  PlotlyHost,
  plotDownloadStem,
} from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
import {
  beginScopedRequest,
  cancelScopedRequest,
  createScopeHolder,
  isAbortError,
  useScopedLoad,
} from "../session/scopedLoad";
import { getPackageMapping } from "../api/mappingApi";
import {
  listRcxPresets,
  postRcxPreset,
  type AnalyticsEnvelope,
} from "../api/analyticsApi";
import {
  comfortDonut,
  meteringCharts,
  multiEquipmentBox,
  multiEquipmentTimeseries,
  oatScatter,
  rankingBars,
  rcxFigureHasFaultLane,
  vavHealthDonut,
  vavHealthWorstBars,
} from "../api/vibeCharts";
import {
  displayUnitLabel,
  resolveRoleUnit,
  type UnitSystem,
} from "../api/roleUnits";
import type { PlotlyFigure } from "../api/plotDataset";
import {
  isOverviewRcxPreset,
  loadOverviewRcxPreset,
  overviewRcxCompanionPngStem,
  overviewRcxPngStem,
} from "../api/rcxOverviewPresets";
import type { RcxPresetTable } from "../api/rcxPresetTables";
import {
  familyPickerOptions,
  REQUIRED_RCX_PRESET_IDS,
} from "../nav/rcxCatalog";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const UNITS_KEY = "openfdd.ui.display_units";

function readUnitSystem(): UnitSystem {
  return localStorage.getItem(UNITS_KEY) === "metric" ? "metric" : "imperial";
}

type RcxPresetRow = {
  id: string;
  title: string;
  family: string;
  chart: string;
  role_col?: string;
  frozen?: boolean;
};

const EMPTY_PRESETS: RcxPresetRow[] = [];
const EMPTY_ROLES: string[] = [];

async function loadPresetRows(site: string, signal: AbortSignal): Promise<RcxPresetRow[]> {
  const listed = await listRcxPresets(site, { signal });
  return listed.filter((row) => row.id);
}

async function loadMappedRoles(site: string, signal: AbortSignal): Promise<string[]> {
  try {
    const inv = await getPackageMapping(site, undefined, { signal });
    const roles = new Set<string>();
    for (const eq of inv.equipment ?? []) {
      for (const role of Object.values(eq.roles ?? {})) {
        if (role) roles.add(String(role));
      }
      for (const col of eq.columns ?? []) {
        if (col.role) roles.add(String(col.role));
      }
    }
    return [...roles];
  } catch (err) {
    if (isAbortError(err)) throw err;
    return [];
  }
}

function rcxYTitle(
  roleCol: string | undefined,
  fallback: string,
  unitSystem: UnitSystem,
): string {
  const role = (roleCol ?? "").trim();
  if (!role) return fallback;
  const unit = resolveRoleUnit(role, unitSystem);
  return unit || role || fallback;
}

function scatterXQuantity(
  coverage: Record<string, unknown> | undefined,
): string {
  const point = coverage?.x_point;
  if (point && typeof point === "object") {
    const quantity = (point as Record<string, unknown>).quantity;
    if (typeof quantity === "string" && quantity.trim()) return quantity.trim();
  }
  const direct = coverage?.x_quantity;
  return typeof direct === "string" ? direct.trim() : "";
}

function rcxScatterXTitle(
  coverage: Record<string, unknown> | undefined,
  unitSystem: UnitSystem,
): string {
  const unit = displayUnitLabel("°F", unitSystem, "temperature");
  if (scatterXQuantity(coverage) === "wet_bulb_temperature") {
    return `Web wet-bulb ${unit}`;
  }
  return `Web dry-bulb ${unit}`;
}

function pointsLookLikeTimeseries(
  points: Array<Record<string, unknown>>,
): boolean {
  return points.some((p) => p.timestamp_utc != null || p.timestamp != null);
}

function fanSummaryTables(
  env: AnalyticsEnvelope | null,
): Array<{ title: string; rows: Array<Record<string, unknown>> }> {
  if (!env) return [];
  const cov = env.coverage;
  const out: Array<{ title: string; rows: Array<Record<string, unknown>> }> = [];
  if (cov && typeof cov === "object") {
    for (const key of ["fan_on", "fan_off", "summary_on", "summary_off", "stats_on", "stats_off"]) {
      const v = cov[key];
      if (Array.isArray(v) && v.length) {
        out.push({
          title: key.replace(/_/g, " "),
          rows: v as Array<Record<string, unknown>>,
        });
      }
    }
  }
  return out;
}

/** vibe19 RCx Plots — preset picker + Timescale analytics series. */
export function RcxPage() {
  const { query } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const presetLoad = useScopedLoad(buildingId, loadPresetRows, EMPTY_PRESETS);
  const roleLoad = useScopedLoad(buildingId, loadMappedRoles, EMPTY_ROLES);
  const presets =
    presetLoad.committedKey === buildingId ? presetLoad.value : EMPTY_PRESETS;
  const mappedRoles = useMemo(() => {
    if (roleLoad.committedKey !== buildingId) return new Set<string>();
    return new Set(roleLoad.value);
  }, [buildingId, roleLoad.committedKey, roleLoad.value]);
  const [family, setFamily] = useState("Zones / VAV");
  const [presetId, setPresetId] = useState("");
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [companionFigure, setCompanionFigure] = useState<PlotlyFigure | null>(
    null,
  );
  const [donutFigure, setDonutFigure] = useState<PlotlyFigure | null>(null);
  const [companionNote, setCompanionNote] = useState<string | null>(null);
  const [presetTables, setPresetTables] = useState<RcxPresetTable[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCoverage, setShowCoverage] = useState(false);
  const [unitSystem, setUnitSystem] = useState<UnitSystem>(readUnitSystem);
  const [chartSite, setChartSite] = useState(buildingId);
  if (chartSite !== buildingId) {
    setChartSite(buildingId);
    setEnv(null);
    setFigure(null);
    setCompanionFigure(null);
    setDonutFigure(null);
    setCompanionNote(null);
    setPresetTables([]);
    setError(null);
  }

  useEffect(() => {
    const onUnits = (event: Event) => {
      const detail = (event as CustomEvent<UnitSystem>).detail;
      if (detail === "metric" || detail === "imperial") setUnitSystem(detail);
    };
    window.addEventListener("openfdd:unit-system-changed", onUnits);
    return () =>
      window.removeEventListener("openfdd:unit-system-changed", onUnits);
  }, []);

  useEffect(() => {
    if (!buildingId || presetLoad.committedKey !== buildingId) return;
    const ok = presetLoad.value;
    setFamily((prev) => {
      if (
        prev &&
        (prev === "Heat pump" || prev === "Weather" || ok.some((x) => x.family === prev))
      ) {
        return prev;
      }
      return "Zones / VAV";
    });
    setPresetId((prev) => {
      if (prev && ok.some((x) => x.id === prev)) return prev;
      const first = ok.find((x) => x.family === "Zones / VAV") ?? ok[0];
      return first?.id || "";
    });
  }, [buildingId, presetLoad.committedKey, presetLoad.value]);

  const families = useMemo(
    () => familyPickerOptions(presets.map((p) => p.family)),
    [presets],
  );
  const familyPresets = useMemo(
    () => presets.filter((p) => !family || p.family === family),
    [presets, family],
  );

  const presetOptions = useMemo(
    () =>
      familyPresets.map((p) => {
        const role = p.role_col?.trim();
        const missing =
          Boolean(buildingId) &&
          Boolean(role) &&
          mappedRoles.size > 0 &&
          !mappedRoles.has(role!);
        return {
          value: p.id,
          label: missing
            ? `${p.title} [${p.chart}] — unavailable (unmapped ${role})`
            : `${p.title} [${p.chart}]`,
          disabled: missing,
        };
      }),
    [familyPresets, buildingId, mappedRoles],
  );

  const coverageRows = useMemo(() => {
    const cov = env?.coverage;
    const observed =
      figure?.meta?.weekly_observations != null
        ? String(figure.meta.weekly_observations)
        : String(figure?.meta?.point_count ?? env?.points?.length ?? 0);
    if (!cov || typeof cov !== "object") {
      return presets.map((p) => ({
        preset_id: p.id,
        title: p.title,
        family: p.family,
        chart: p.chart,
        frozen: p.frozen ? "yes" : "no",
        status: "listed",
        points: "—",
        note: "",
      }));
    }
    const runId = String(cov.preset_id ?? presetId);
    return [
      {
        preset_id: runId,
        title: String(cov.title ?? ""),
        family: String(cov.family ?? ""),
        chart: String(cov.chart_kind ?? cov.chart ?? ""),
        frozen: presets.find((p) => p.id === runId)?.frozen ? "yes" : "no",
        status: cov.empty ? "empty" : "ok",
        points: observed,
        note: [
          cov.role_col != null ? `role=${cov.role_col}` : "",
          cov.y_col != null ? `y=${cov.y_col}` : "",
          cov.meter_kind != null ? `meter=${cov.meter_kind}` : "",
          ...(env?.warnings ?? []),
        ]
          .filter(Boolean)
          .join(" · "),
      },
      ...Object.entries(cov)
        .filter(
          ([k]) =>
            ![
              "preset_id",
              "title",
              "family",
              "chart_kind",
              "chart",
              "role_col",
              "y_col",
              "meter_kind",
              "empty",
            ].includes(k),
        )
        .map(([k, v]) => ({
          preset_id: runId,
          title: k,
          family: "",
          chart: "",
          frozen: "",
          status: "field",
          points: typeof v === "object" ? JSON.stringify(v) : String(v ?? ""),
          note: "",
        })),
    ];
  }, [env, figure, presets, presetId]);

  const runHolder = useRef(createScopeHolder());
  const familyPresetsRef = useRef(familyPresets);
  familyPresetsRef.current = familyPresets;

  const run = useCallback(async (opts?: { refresh?: boolean }) => {
    if (!buildingId || !presetId) return;
    const ticket = beginScopedRequest(runHolder.current);
    const live = () => ticket.isCurrent();
    setLoading(true);
    setError(null);
    setCompanionFigure(null);
    setDonutFigure(null);
    setCompanionNote(null);
    setPresetTables([]);
    try {
      if (isOverviewRcxPreset(presetId)) {
        const loaded = await loadOverviewRcxPreset(
          buildingId,
          presetId,
          undefined,
          opts?.refresh,
          unitSystem,
          ticket.signal,
        );
        if (!live()) return;
        setEnv(loaded.env);
        setFigure(loaded.figure);
        setCompanionFigure(loaded.companion);
        setPresetTables(loaded.tables);
        if (loaded.error && !loaded.figure) setError(loaded.error);
        return;
      }
      const res = await postRcxPreset(
        {
          building_id: buildingId,
          max_points: 8000,
          series: { preset_id: presetId },
          ...(opts?.refresh ? { refresh: true } : {}),
        },
        { signal: ticket.signal },
      );
      if (!live()) return;
      setEnv(res);
      const listed = familyPresetsRef.current;
      const title =
        String(res.coverage?.title ?? presetId) ||
        listed.find((p) => p.id === presetId)?.title ||
        presetId;
      const kind = String(
        res.coverage?.chart_kind ??
          listed.find((p) => p.id === presetId)?.chart ??
          "",
      );
      const schema = String(res.coverage?.schema_version ?? "");
      const qv = String(res.query_version ?? "");
      const isVavHealth =
        kind === "vav_health" ||
        schema === "vav_health_matrix_v1" ||
        qv === "vav-health-v1" ||
        presetId === "vav_health_matrix";
      const points = res.points ?? [];
      const matrixRows = res.rows ?? [];
      if (isVavHealth) {
        if (!matrixRows.length) {
          setFigure(null);
          setError(
            res.warnings?.[0] ?? "No VAV health rows — preset returned empty.",
          );
          return;
        }
        const fig = vavHealthWorstBars(matrixRows, {
          title,
          yTitle: "comfort fail h",
        });
        setDonutFigure(
          vavHealthDonut(matrixRows, { title: "VAV health boxes" }),
        );
        const brokenUnknown = matrixRows.some(
          (r) => r.broken_box === null || r.broken_box === undefined,
        );
        if (brokenUnknown) {
          setCompanionNote(
            "Broken-box flags unknown until Run all rules joins VAV FDD results.",
          );
        } else {
          setCompanionNote(null);
        }
        if (rcxFigureHasFaultLane(fig)) {
          setFigure(null);
          setError("Internal: RCx figure must not include a fault lane");
          return;
        }
        setFigure(fig);
        return;
      }
      if (!points.length) {
        setFigure(null);
        setError(res.warnings?.[0] ?? "No points — preset returned empty.");
        return;
      }
      let fig: PlotlyFigure | null = null;
      const roleCol = String(res.coverage?.role_col ?? res.coverage?.y_col ?? "");
      const unitTitle = rcxYTitle(roleCol, "value", unitSystem);
      if (kind === "scatter_oat") {
        fig = oatScatter(points, {
          title,
          yTitle: unitTitle,
          xTitle: rcxScatterXTitle(
            res.coverage as Record<string, unknown>,
            unitSystem,
          ),
          unitSystem,
        });
      } else if (kind === "box") {
        fig = multiEquipmentBox(points, {
          title,
          yTitle: unitTitle,
          unitSystem,
        });
      } else if (kind === "ranking") {
        fig = rankingBars(points, {
          title,
          yTitle: "% time in comfort band",
          sort: "asc",
        });
        const rankRows = res.rows?.length ? res.rows : points;
        setDonutFigure(
          comfortDonut(rankRows, { title: "Zone comfort band" }),
        );
        if (pointsLookLikeTimeseries(points)) {
          setCompanionFigure(
            multiEquipmentTimeseries(points, {
              title: "Worst zones — space temp",
              yTitle: unitTitle || "zone_t",
              unitSystem,
            }),
          );
        } else {
          setCompanionNote(
            "Worst-zones timeseries is not in this envelope (ranking points are fail %). Use the zone_temps preset for space-temp series.",
          );
        }
      } else if (kind === "metering") {
        const gas = String(res.coverage?.meter_kind ?? "") === "gas";
        fig = meteringCharts(points, {
          title,
          ddLabel: gas ? "HDD" : "CDD",
          energyYTitle: gas ? "gas" : "kWh",
        });
      } else {
        fig = multiEquipmentTimeseries(points, {
          title,
          yTitle: unitTitle,
          unitSystem,
        });
      }
      if (rcxFigureHasFaultLane(fig)) {
        setFigure(null);
        setError("Internal: RCx figure must not include a fault lane");
        return;
      }
      setFigure(fig);
      if (kind !== "ranking") {
        const fan = fanSummaryTables(res);
        if (fan.length) {
          setCompanionNote(null);
        } else if (kind === "timeseries" && /fan/i.test(presetId)) {
          setCompanionNote(
            "Fan on/off summary stats are not in this preset envelope.",
          );
        }
      }
    } catch (err) {
      if (!live() || isAbortError(err)) return;
      setError(formatErr(err));
      setFigure(null);
    } finally {
      if (live()) setLoading(false);
    }
  }, [buildingId, presetId, unitSystem]);

  const presetsReady = Boolean(buildingId) && presetLoad.committedKey === buildingId;
  useEffect(() => {
    const runScope = runHolder.current;
    if (!presetsReady || !presetId) return;
    if (!presets.some((preset) => preset.id === presetId)) return;
    void run();
    return () => cancelScopedRequest(runScope);
  }, [presetsReady, presetId, presets, run]);

  const emptyFamily = familyPresets.length === 0;
  const fanTables = fanSummaryTables(env);

  return (
    <AppShell
      title="RCx Plots"
      caption="Retro-commissioning presets from the canonical historian. CSV and portal samples use the same charts."
      activeSectionId="rcx-plots"
    >
      <div className="page-stack" data-testid="rcx-page">
        <LockedSiteCaption buildingId={buildingId} />
        <p data-testid="rcx-required-ids" hidden>
          {REQUIRED_RCX_PRESET_IDS.join(",")}
        </p>
        <Select
          id="rcx-family"
          label="Family"
          value={family}
          options={families.map((f) => ({ value: f, label: f }))}
          onChange={(v) => {
            setFamily(v);
            const next = presets.find((p) => p.family === v);
            setPresetId(next?.id ?? "");
            setFigure(null);
            setEnv(null);
            setPresetTables([]);
          }}
          testId="rcx-family"
        />
        {emptyFamily ? (
          <InlineAlert id="rcx-empty-family" variant="info" testId="rcx-empty-family">
            No RCx chart presets in <strong>{family}</strong> yet.
          </InlineAlert>
        ) : (
          <Select
            id="rcx-preset"
            label="Preset"
            value={presetOptions.some((opt) => opt.value === presetId) ? presetId : ""}
            options={
              presetOptions.some((opt) => opt.value === presetId)
                ? presetOptions
                : [{ value: "", label: "— preset —" }, ...presetOptions]
            }
            onChange={setPresetId}
            testId="rcx-preset"
          />
        )}
        <Checkbox
          id="rcx-coverage"
          label="Show preset coverage diagnostics"
          checked={showCoverage}
          onChange={setShowCoverage}
          testId="rcx-coverage-toggle"
        />
        <Button
          id="rcx-run"
          label={loading ? "Running…" : "Refresh RCx preset"}
          onClick={() => void run({ refresh: true })}
          disabled={!buildingId || !presetId || loading || emptyFamily}
          testId="rcx-run"
        />
        {error ? (
          <InlineAlert id="rcx-error" variant="danger" testId="rcx-error">
            {error}
          </InlineAlert>
        ) : null}
        {env ? (
          <p className="oracle-sidebar__caption" data-testid="rcx-provenance">
            engine={env.engine} · {env.query_version}
            {figure?.meta?.weekly_observations != null && figure.meta.provenance
              ? ` · ${figure.meta.provenance}`
              : ` · points=${figure?.meta?.point_count ?? env.points?.length ?? 0}`}
            {env.warnings?.[0] ? ` · ${env.warnings[0]}` : ""}
          </p>
        ) : null}
        {showCoverage ? (
          <DataTable
            id="rcx-coverage"
            label="Preset coverage diagnostics"
            columns={[
              { key: "preset_id", header: "Preset" },
              { key: "title", header: "Title / field" },
              { key: "family", header: "Family" },
              { key: "chart", header: "Chart" },
              { key: "frozen", header: "Frozen" },
              { key: "status", header: "Status" },
              { key: "points", header: "Points / value" },
              { key: "note", header: "Note" },
            ]}
            rows={coverageRows}
            testId="rcx-coverage-table"
          />
        ) : null}
        <PlotlyHost
          id="rcx-plot"
          label="RCx chart"
          figure={figure}
          loading={loading}
          height={420}
          downloadFilename={
            isOverviewRcxPreset(presetId)
              ? overviewRcxPngStem(presetId)
              : plotDownloadStem(
                  "rcx",
                  family || undefined,
                  presetId || "preset",
                )
          }
          testId="rcx-plot"
        />
        <SeriesPreview
          id="rcx-plot-preview"
          figure={figure}
          testId="rcx-plot-preview"
        />
        {donutFigure ? (
          <PlotlyHost
            id="rcx-comfort-donut"
            label="Comfort donut"
            figure={donutFigure}
            height={320}
            downloadFilename="rcx_comfort_donut"
            testId="rcx-comfort-donut"
          />
        ) : null}
        <SeriesPreview
          id="rcx-donut-preview"
          figure={donutFigure}
          testId="rcx-donut-preview"
        />
        {companionFigure ? (
          <PlotlyHost
            id="rcx-worst-zones"
            label="Worst zones timeseries"
            figure={companionFigure}
            height={360}
            downloadFilename={
              overviewRcxCompanionPngStem(presetId) ?? "rcx_worst_zones"
            }
            testId="rcx-worst-zones"
          />
        ) : null}
        <SeriesPreview
          id="rcx-companion-preview"
          figure={companionFigure}
          testId="rcx-companion-preview"
        />
        {companionNote ? (
          <p className="oracle-sidebar__caption" data-testid="rcx-companion-note">
            {companionNote}
          </p>
        ) : null}
        {fanTables.map((t) => (
          <DataTable
            key={t.title}
            id={`rcx-fan-${t.title}`}
            label={`Fan / air ${t.title}`}
            columns={Object.keys(t.rows[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={t.rows.slice(0, 80) as Array<Record<string, string | number>>}
            testId={`rcx-fan-${t.title.replace(/\s+/g, "-")}`}
          />
        ))}
        {presetTables.map((t) => (
          <DataTable
            key={t.id}
            id={`rcx-preset-${t.id}`}
            label={t.label}
            columns={Object.keys(t.rows[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={t.rows.slice(0, 200) as Array<Record<string, string | number>>}
            testId={`rcx-preset-table-${t.id}`}
          />
        ))}
        {!presetTables.length && env?.rows?.length ? (
          <DataTable
            id="rcx-rows"
            label="RCx stats"
            columns={Object.keys(env.rows[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={
              env.rows.slice(0, 80) as Array<Record<string, string | number>>
            }
            testId="rcx-rows-table"
          />
        ) : !presetTables.length && env?.points?.length ? (
          <DataTable
            id="rcx-points"
            label="RCx points (sample)"
            columns={Object.keys(env.points[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={
              env.points.slice(0, 80) as Array<Record<string, string | number>>
            }
            testId="rcx-points-table"
          />
        ) : null}
      </div>
    </AppShell>
  );
}
