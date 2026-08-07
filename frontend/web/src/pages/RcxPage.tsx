import { useEffect, useMemo, useState } from "react";
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
import { listPackageBuildings } from "../api/mappingApi";
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
} from "../api/vibeCharts";
import type { PlotlyFigure } from "../api/plotDataset";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** vibe19 RCx Plots — preset picker + DataFusion historian series. */
export function RcxPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const [buildings, setBuildings] = useState<string[]>([]);
  const [presets, setPresets] = useState<
    Array<{
      id: string;
      title: string;
      family: string;
      chart: string;
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

  const families = useMemo(
    () => [...new Set(presets.map((p) => p.family))].sort(),
    [presets],
  );
  const familyPresets = useMemo(
    () => presets.filter((p) => !family || p.family === family),
    [presets, family],
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

  const run = async () => {
    if (!buildingId || !presetId) return;
    setLoading(true);
    setError(null);
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
        if (res.warnings?.length) setError(res.warnings[0] ?? "No points");
        return;
      }
      let fig: PlotlyFigure | null = null;
      if (kind === "scatter_oat") {
        fig = oatScatter(points, {
          title,
          yTitle: String(res.coverage?.y_col ?? "value"),
        });
      } else if (kind === "box") {
        fig = multiEquipmentBox(points, {
          title,
          yTitle: String(res.coverage?.role_col ?? "value"),
        });
      } else if (kind === "ranking") {
        fig = rankingBars(points, { title });
      } else if (kind === "metering") {
        fig = meteringCharts(points, {
          title,
          ddLabel:
            String(res.coverage?.meter_kind ?? "") === "gas" ? "HDD" : "CDD",
        });
      } else {
        fig = multiEquipmentTimeseries(points, {
          title,
          yTitle: String(res.coverage?.role_col ?? "value"),
        });
      }
      setFigure(fig);
    } catch (err) {
      setError(formatErr(err));
      setFigure(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell
      title="RCx Plots"
      caption="Retro-commissioning presets via central DataFusion historian (vibe19 chart kinds)."
      activeSectionId="rcx-plots"
    >
      <div className="page-stack" data-testid="rcx-page">
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
          label="Family"
          value={family}
          options={[
            { value: "", label: "— all —" },
            ...families.map((f) => ({ value: f, label: f })),
          ]}
          onChange={(v) => {
            setFamily(v);
            const next = presets.find((p) => !v || p.family === v);
            if (next) setPresetId(next.id);
          }}
          testId="rcx-family"
        />
        <Select
          id="rcx-preset"
          label="Preset"
          value={presetId}
          options={familyPresets.map((p) => ({
            value: p.id,
            label: `${p.title} [${p.chart}]`,
          }))}
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
          id="rcx-plot"
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
