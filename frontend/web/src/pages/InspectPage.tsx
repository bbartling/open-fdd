import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import { LockedSiteCaption } from "../components/LockedSiteCaption";
import { Button, InlineAlert, Select } from "../components/widgets";
import { PlotlyHost } from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
import { postInspect } from "../api/analyticsApi";
import { getPackageMapping } from "../api/mappingApi";
import { equipmentInspectionChart } from "../api/inspectChart";
import { downloadRowsCsv } from "../api/csvDownload";
import { naturalCompare } from "../lib/naturalSort";
import type { PlotlyFigure } from "../api/plotDataset";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** CSV / equipment overlay plot (moved off Overview). */
export function InspectPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";
  const [options, setOptions] = useState<string[]>([]);
  const [pick, setPick] = useState(equipmentId);
  const [cols, setCols] = useState<string[]>([]);
  const [selectedCols, setSelectedCols] = useState<string[]>([]);
  const [fig, setFig] = useState<PlotlyFigure | null>(null);
  const [meta, setMeta] = useState<{ row_count: number; span: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (!buildingId) {
      setOptions([]);
      setPick("");
      return;
    }
    void getPackageMapping(buildingId)
      .then((inv) => {
        const ids = [
          ...new Set(
            (inv.equipment ?? [])
              .map((e) => String(e.equipment_id ?? ""))
              .filter(Boolean)
              .sort(naturalCompare),
          ),
        ];
        // Always replace options for the active site — never keep prior building's list.
        setOptions(ids);
        setPick((prev) => {
          if (equipmentId && ids.includes(equipmentId)) return equipmentId;
          if (prev && ids.includes(prev)) return prev;
          return ids[0] || "";
        });
      })
      .catch(() => {
        setOptions([]);
        setPick("");
        setErr(`No historian mapping for site ${buildingId}`);
      });
  }, [buildingId, equipmentId]);

  const refresh = useCallback(
    async (opts?: { pick?: string; cols?: string[] }) => {
      const usePick = opts?.pick ?? pick;
      if (!buildingId || !usePick || usePick === "(weather)") return;
      const n = ++seq.current;
      setBusy(true);
      setErr(null);
      try {
        const requested = opts?.cols ?? [];
        const env = await postInspect({
          building_id: buildingId,
          equipment_ids: [usePick],
          max_points: 8000,
          series: {
            columns: requested.length > 0 ? requested : undefined,
          },
        });
        if (n !== seq.current) return;
        const cov = (env.coverage ?? {}) as Record<string, unknown>;
        const plottable = Array.isArray(cov.plottable_columns)
          ? (cov.plottable_columns as string[])
          : [];
        const plotted = Array.isArray(cov.columns_plotted)
          ? (cov.columns_plotted as string[])
          : [];
        const allCols = plottable.length ? plottable : plotted;
        setCols(allCols);
        const sampleN = Number(env.points?.length ?? cov.point_count ?? 0);
        const first =
          cov.first_timestamp != null ? String(cov.first_timestamp) : null;
        const last =
          cov.last_timestamp != null ? String(cov.last_timestamp) : null;
        setMeta({
          row_count: Number.isFinite(sampleN) ? sampleN : 0,
          span: first && last ? `${first} → ${last}` : "—",
        });
        if (
          !requested.length &&
          plottable.length &&
          plotted.length < plottable.length
        ) {
          void refresh({ pick: usePick, cols: plottable });
          return;
        }
        if (env.warnings?.length && !env.points?.length) {
          setFig(null);
          setErr(env.warnings[0] ?? "Inspection unavailable");
          return;
        }
        const colsForChart = (requested.length ? requested : plotted).filter(
          (c) =>
            plottable.includes(c) || plotted.includes(c) || !plottable.length,
        );
        setSelectedCols(colsForChart.length ? colsForChart : plotted);
        const next = equipmentInspectionChart(env.points ?? [], {
          equipmentId: usePick,
          columns: colsForChart.length ? colsForChart : plotted,
        });
        setFig(next);
        setErr(
          next
            ? null
            : "No plottable numeric columns for this equipment in historian Parquet.",
        );
      } catch (e) {
        if (n !== seq.current) return;
        setErr(formatErr(e));
        setFig(null);
      } finally {
        if (n === seq.current) setBusy(false);
      }
    },
    [buildingId, pick],
  );

  useEffect(() => {
    if (buildingId && pick) void refresh({ pick });
  }, [buildingId, pick, refresh]);

  return (
    <AppShell
      title="Inspect"
      caption="Raw CSV / equipment overlay from historian Parquet."
      activeSectionId="inspect"
    >
      <div className="page-stack" data-testid="inspect-page">
        <LockedSiteCaption buildingId={buildingId} />
        <section className="overview-section" data-testid="overview-data-inspection">
          <h3>Data inspection — raw CSV</h3>
          <p className="oracle-sidebar__caption">
            Pick any uploaded equipment (or weather) CSV and plot numeric / status
            columns as stacked Plotly line charts.
          </p>
          <Select
            id="inspect-eq"
            label="CSV / equipment"
            value={pick}
            options={(options.length ? options : pick ? [pick] : []).map((id) => ({
              value: id,
              label: id,
            }))}
            onChange={(v) => {
              setPick(v);
              setQuery({ equipment: v }, true);
              void refresh({ pick: v });
            }}
            testId="overview-inspect-eq"
          />
          <p className="oracle-sidebar__caption" data-testid="overview-inspect-meta">
            {pick || "—"} · chart sample {meta?.row_count ?? 0} points ·{" "}
            {cols.length} plottable columns
            {meta?.span ? ` · ${meta.span}` : ""}
          </p>
          {err ? (
            <InlineAlert id="inspect-err" variant="danger" testId="inspect-err">
              {err}
            </InlineAlert>
          ) : null}
          <PlotlyHost
            id="data-inspect"
            label="Inspection chart"
            figure={fig}
            loading={busy}
            height={Math.min(
              4000,
              Math.max(280, (selectedCols.length || cols.length || 1) * 160),
            )}
            downloadFilename={`${pick || "equipment"}_inspect`}
            testId="overview-inspect-plot"
          />
          <Button
            id="dl-inspect"
            label={`Download \`${pick || "csv"}\` JSON sample`}
            variant="secondary"
            disabled={!fig?.data?.length}
            onClick={() => {
              const rows = fig?.data?.[0] as
                | { x?: unknown[]; y?: unknown[] }
                | undefined;
              if (!rows?.x?.length) return;
              const preview = rows.x.map((x, i) => ({
                timestamp: x,
                value: rows.y?.[i] ?? null,
              }));
              downloadRowsCsv(`${pick || "equipment"}_series.csv`, preview);
            }}
            testId="overview-dl-inspect"
          />
        </section>
      </div>
    </AppShell>
  );
}
