import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "../components/AppShell";
import { LockedSiteCaption } from "../components/LockedSiteCaption";
import {
  InlineAlert,
  Select,
  Button,
  DataTable,
  Checkbox,
} from "../components/widgets";
import { PlotlyHost } from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
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
} from "../api/vibeCharts";
import { resolveRoleUnit } from "../api/roleUnits";
import type { PlotlyFigure } from "../api/plotDataset";
import {
  familyPickerOptions,
  REQUIRED_RCX_PRESET_IDS,
} from "../nav/rcxCatalog";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function rcxYTitle(roleCol: string | undefined, fallback: string): string {
  const role = (roleCol ?? "").trim();
  if (!role) return fallback;
  const unit = resolveRoleUnit(role);
  return unit || role || fallback;
}

function rcxScatterXTitle(coverage: Record<string, unknown> | undefined): string {
  if (coverage?.prefer_wetbulb === true) return "Web wet-bulb °F";
  const oat = String(coverage?.oat_column ?? "");
  if (oat.includes("wb") || oat.includes("wet")) return "Web wet-bulb °F";
  return "Web dry-bulb °F";
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

/** vibe19 RCx Plots — preset picker + DataFusion historian series. */
export function RcxPage() {
  const { query } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const [mappedRoles, setMappedRoles] = useState<Set<string>>(new Set());
  const [presets, setPresets] = useState<
    Array<{
      id: string;
      title: string;
      family: string;
      chart: string;
      role_col?: string;
      frozen?: boolean;
    }>
  >([]);
  const [family, setFamily] = useState("Zones / VAV");
  const [presetId, setPresetId] = useState("");
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [companionFigure, setCompanionFigure] = useState<PlotlyFigure | null>(
    null,
  );
  const [donutFigure, setDonutFigure] = useState<PlotlyFigure | null>(null);
  const [companionNote, setCompanionNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCoverage, setShowCoverage] = useState(false);

  useEffect(() => {
    void listRcxPresets()
      .then((p) => {
        const ok = p.filter((x) => x.id);
        setPresets(ok);
        setFamily((prev) => {
          if (prev && (prev === "Heat pump" || prev === "Weather" || ok.some((x) => x.family === prev))) {
            return prev;
          }
          return "Zones / VAV";
        });
        setPresetId((prev) => {
          if (prev && ok.some((x) => x.id === prev)) return prev;
          const first = ok.find((x) => x.family === "Zones / VAV") ?? ok[0];
          return first?.id || "";
        });
      })
      .catch(() => setPresets([]));
  }, []);

  useEffect(() => {
    if (!buildingId) {
      setMappedRoles(new Set());
      return;
    }
    void getPackageMapping(buildingId)
      .then((inv) => {
        const roles = new Set<string>();
        for (const eq of inv.equipment ?? []) {
          for (const role of Object.values(eq.roles ?? {})) {
            if (role) roles.add(String(role));
          }
          for (const col of eq.columns ?? []) {
            if (col.role) roles.add(String(col.role));
          }
        }
        setMappedRoles(roles);
      })
      .catch(() => setMappedRoles(new Set()));
  }, [buildingId]);

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
        points: String(env?.points?.length ?? 0),
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
  }, [env, presets, presetId]);

  const run = useCallback(async () => {
    if (!buildingId || !presetId) return;
    setLoading(true);
    setError(null);
    setCompanionFigure(null);
    setDonutFigure(null);
    setCompanionNote(null);
    try {
      const res = await postRcxPreset({
        building_id: buildingId,
        max_points: 8000,
        series: { preset_id: presetId },
      });
      setEnv(res);
      const title =
        String(res.coverage?.title ?? presetId) ||
        familyPresets.find((p) => p.id === presetId)?.title ||
        presetId;
      const kind = String(
        res.coverage?.chart_kind ??
          familyPresets.find((p) => p.id === presetId)?.chart ??
          "",
      );
      const points = res.points ?? [];
      if (!points.length) {
        setFigure(null);
        setError(res.warnings?.[0] ?? "No points — preset returned empty.");
        return;
      }
      let fig: PlotlyFigure | null = null;
      const roleCol = String(res.coverage?.role_col ?? res.coverage?.y_col ?? "");
      const unitTitle = rcxYTitle(roleCol, "value");
      if (kind === "scatter_oat") {
        fig = oatScatter(points, {
          title,
          yTitle: unitTitle,
          xTitle: rcxScatterXTitle(res.coverage as Record<string, unknown>),
        });
      } else if (kind === "box") {
        fig = multiEquipmentBox(points, {
          title,
          yTitle: unitTitle,
        });
      } else if (kind === "ranking") {
        fig = rankingBars(points, {
          title,
          yTitle: "comfort fail %",
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
      setError(formatErr(err));
      setFigure(null);
    } finally {
      setLoading(false);
    }
  }, [buildingId, presetId, familyPresets]);

  useEffect(() => {
    if (!buildingId || !presetId) return;
    if (family === "Heat pump" || family === "Weather") return;
    void run();
  }, [buildingId, presetId, family, run]);

  const emptyFamily = family === "Heat pump" || family === "Weather";
  const fanTables = fanSummaryTables(env);

  return (
    <AppShell
      title="RCx Plots"
      caption="Retro-commissioning presets via central DataFusion historian (vibe19 chart kinds)."
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
          }}
          testId="rcx-family"
        />
        {emptyFamily ? (
          <InlineAlert id="rcx-empty-family" variant="info" testId="rcx-empty-family">
            No RCx chart presets in <strong>{family}</strong> yet — Heat pump /
            Weather are placeholders until presets exist.
          </InlineAlert>
        ) : (
          <Select
            id="rcx-preset"
            label="Preset"
            value={presetId}
            options={presetOptions}
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
          onClick={() => void run()}
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
            engine={env.engine} · {env.query_version} · points=
            {env.points?.length ?? 0}
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
          testId="rcx-plot"
        />
        {donutFigure ? (
          <PlotlyHost
            id="rcx-comfort-donut"
            label="Comfort donut"
            figure={donutFigure}
            height={320}
            testId="rcx-comfort-donut"
          />
        ) : null}
        {companionFigure ? (
          <PlotlyHost
            id="rcx-worst-zones"
            label="Worst zones timeseries"
            figure={companionFigure}
            height={360}
            testId="rcx-worst-zones"
          />
        ) : null}
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
        {env?.rows?.length ? (
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
        ) : env?.points?.length ? (
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
