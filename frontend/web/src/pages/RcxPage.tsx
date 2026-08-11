import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import {
  InlineAlert,
  Select,
  Button,
  DataTable,
  Checkbox,
} from "../components/widgets";
import { PlotlyHost } from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
import { getPackageMapping, listPackageBuildings } from "../api/mappingApi";
import {
  listRcxPresets,
  postRcxPreset,
  type AnalyticsEnvelope,
} from "../api/analyticsApi";
import {
  meteringCharts,
  multiEquipmentBox,
  multiEquipmentTimeseries,
  oatScatter,
  rankingBars,
  rcxFigureHasFaultLane,
} from "../api/vibeCharts";
import { resolveRoleUnit } from "../api/roleUnits";
import type { PlotlyFigure } from "../api/plotDataset";

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

/** vibe19 RCx Plots — preset picker + DataFusion historian series. */
export function RcxPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const [buildings, setBuildings] = useState<string[]>([]);
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
  const [family, setFamily] = useState("");
  const [presetId, setPresetId] = useState("");
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCoverage, setShowCoverage] = useState(false);
  const runSeq = useRef(0);

  useEffect(() => {
    void listPackageBuildings()
      .then(setBuildings)
      .catch(() => setBuildings([]));
    void listRcxPresets()
      .then((p) => {
        const ok = p.filter((x) => x.id);
        setPresets(ok);
        setFamily((prev) => prev || ok[0]?.family || "");
        setPresetId((prev) => prev || ok[0]?.id || "");
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
    () => [...new Set(presets.map((p) => p.family))].sort(),
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
    const seq = ++runSeq.current;
    setLoading(true);
    setError(null);
    try {
      const res = await postRcxPreset({
        building_id: buildingId,
        max_points: 8000,
        series: { preset_id: presetId },
      });
      if (seq !== runSeq.current) return;
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
        if (res.warnings?.length) setError(res.warnings[0] ?? "No points");
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
    } catch (err) {
      if (seq !== runSeq.current) return;
      setError(formatErr(err));
      setFigure(null);
    } finally {
      if (seq === runSeq.current) setLoading(false);
    }
  }, [buildingId, familyPresets, presetId]);

  useEffect(() => {
    if (!buildingId || !presetId) return;
    void run();
  }, [buildingId, presetId, run]);

  return (
    <AppShell
      title="RCx plots"
      caption="Pick a mechanical family, then one plot. AHU timeseries keep every unit on one figure."
      activeSectionId="rcx-plots"
    >
      <div className="page-stack" data-testid="rcx-page">
        <h2>RCx plots</h2>
        <Select
          id="rcx-building"
          label="Building"
          value={buildingId}
          options={[
            { value: "", label: "— select —" },
            ...buildings.map((b) => ({ value: b, label: b })),
          ]}
          onChange={(v) => setQuery({ siteId: v || undefined }, true)}
          testId="rcx-building"
        />
        <Select
          id="rcx-family"
          label="Mechanical family"
          value={family}
          options={families.map((f) => ({ value: f, label: f }))}
          onChange={(v) => {
            setFamily(v);
            const next = presets.find((p) => p.family === v);
            if (next) setPresetId(next.id);
          }}
          testId="rcx-family"
        />
        <Select
          id="rcx-preset"
          label="Plot"
          value={presetId}
          options={presetOptions}
          onChange={setPresetId}
          testId="rcx-preset"
        />
        <Checkbox
          id="rcx-coverage"
          label="Show preset coverage diagnostics"
          checked={showCoverage}
          onChange={setShowCoverage}
          testId="rcx-coverage-toggle"
        />
        <Button
          id="rcx-run"
          label={loading ? "Running…" : "Run RCx preset"}
          onClick={() => void run()}
          disabled={!buildingId || !presetId || loading}
          testId="rcx-run"
        />
        {error ? (
          <InlineAlert id="rcx-error" variant="danger">
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
          key={`rcx-${presetId || "none"}`}
          id="rcx-plot"
          figureId={`rcx-${presetId || "none"}`}
          label="RCx chart"
          figure={figure}
          loading={loading}
          height={420}
          testId="rcx-plot"
        />
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
