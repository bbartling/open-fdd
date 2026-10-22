import { useEffect, useMemo, useRef } from "react";
import { AppShell } from "../components/AppShell";
import { LockedSiteCaption } from "../components/LockedSiteCaption";
import { Button, InlineAlert, Select } from "../components/widgets";
import { PlotlyHost } from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
import { postInspect, type AnalyticsEnvelope } from "../api/analyticsApi";
import { getPackageMapping, type MappingEquipment } from "../api/mappingApi";
import { equipmentInspectionChart } from "../api/inspectChart";
import { downloadRowsCsv } from "../api/csvDownload";
import { naturalCompare } from "../lib/naturalSort";
import type { PlotlyFigure } from "../api/plotDataset";
import { useScopedLoad } from "../session/scopedLoad";

type InspectChoice = { id: string; columns: string[] };

type InspectSnapshot = {
  columns: string[];
  selected: string[];
  figure: PlotlyFigure | null;
  rowCount: number;
  span: string;
  error: string | null;
};

const EMPTY_CHOICES: InspectChoice[] = [];

const EMPTY_SNAPSHOT: InspectSnapshot = {
  columns: [],
  selected: [],
  figure: null,
  rowCount: 0,
  span: "",
  error: null,
};

function choiceColumns(eq: MappingEquipment): string[] {
  const columns = new Set<string>();
  for (const role of Object.values(eq.roles ?? {})) {
    if (role) columns.add(String(role));
  }
  for (const col of eq.columns ?? []) {
    if (col.role) columns.add(String(col.role));
  }
  return [...columns];
}

function choicesFromEquipment(equipment: MappingEquipment[] | undefined): InspectChoice[] {
  const byId = new Map<string, InspectChoice>();
  for (const eq of equipment ?? []) {
    const id = String(eq.equipment_id ?? "");
    if (!id || byId.has(id)) continue;
    byId.set(id, { id, columns: choiceColumns(eq) });
  }
  return [...byId.values()].sort((a, b) => naturalCompare(a.id, b.id));
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

/** One historian read. Mapped roles are requested up front so a second query is not required. */
function snapshotFromInspect(env: AnalyticsEnvelope, equipmentId: string): InspectSnapshot {
  const cov = (env.coverage ?? {}) as Record<string, unknown>;
  const plottable = stringList(cov.plottable_columns);
  const plotted = stringList(cov.columns_plotted);
  const columns = plottable.length ? plottable : plotted;
  const sampleN = Number(env.points?.length ?? cov.point_count ?? 0);
  const first = cov.first_timestamp != null ? String(cov.first_timestamp) : null;
  const last = cov.last_timestamp != null ? String(cov.last_timestamp) : null;
  const span = first && last ? `${first} → ${last}` : "";
  const rowCount = Number.isFinite(sampleN) ? sampleN : 0;
  if (env.warnings?.length && !env.points?.length) {
    return {
      columns,
      selected: [],
      figure: null,
      rowCount,
      span,
      error: env.warnings[0] ?? "Inspection unavailable",
    };
  }
  const selected = plotted.filter((col) => plottable.includes(col) || !plottable.length);
  const chartColumns = selected.length ? selected : plotted;
  const figure = equipmentInspectionChart(env.points ?? [], {
    equipmentId,
    columns: chartColumns,
  });
  return {
    columns,
    selected: chartColumns,
    figure,
    rowCount,
    span,
    error: figure ? null : "No plottable numeric columns for this equipment in Timescale.",
  };
}

/** CSV / equipment overlay plot (moved off Overview). */
export function InspectPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";
  const columnsById = useRef(new Map<string, string[]>());

  const choiceLoad = useScopedLoad(
    buildingId,
    async (site, signal) => {
      const inv = await getPackageMapping(site, undefined, { signal });
      return choicesFromEquipment(inv.equipment);
    },
    EMPTY_CHOICES,
  );

  const choices =
    choiceLoad.committedKey === buildingId ? choiceLoad.value : EMPTY_CHOICES;
  columnsById.current = new Map(choices.map((choice) => [choice.id, choice.columns]));

  useEffect(() => {
    if (!buildingId || choiceLoad.committedKey !== buildingId) return;
    const ids = choiceLoad.value.map((choice) => choice.id);
    if (equipmentId && ids.includes(equipmentId)) return;
    const next = ids[0] ?? "";
    if (next !== equipmentId) setQuery({ equipment: next }, true);
  }, [buildingId, choiceLoad.committedKey, choiceLoad.value, equipmentId, setQuery]);

  const selected = choices.find((choice) => choice.id === equipmentId) ?? null;
  const inspectKey = selected ? `${buildingId}\u0000${equipmentId}` : "";
  const chartLoad = useScopedLoad(
    inspectKey,
    async (key, signal) => {
      const split = key.indexOf("\u0000");
      const site = key.slice(0, split);
      const eq = key.slice(split + 1);
      const columns = columnsById.current.get(eq) ?? [];
      const env = await postInspect(
        {
          building_id: site,
          equipment_ids: [eq],
          max_points: 8000,
          ...(columns.length ? { series: { columns } } : {}),
        },
        { signal },
      );
      return snapshotFromInspect(env, eq);
    },
    EMPTY_SNAPSHOT,
  );

  const snap = chartLoad.committedKey === inspectKey ? chartLoad.value : EMPTY_SNAPSHOT;
  const err = snap.error ?? chartLoad.error ?? choiceLoad.error;
  const selectValue = selected ? equipmentId : "";
  const options = useMemo(() => {
    const rows = choices.map((choice) => ({ value: choice.id, label: choice.id }));
    if (selectValue) return rows;
    return [{ value: "", label: "— equipment —" }, ...rows];
  }, [choices, selectValue]);

  return (
    <AppShell
      title="Inspect"
      caption="Raw CSV / equipment overlay from the Timescale historian."
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
            value={selectValue}
            options={options}
            onChange={(value) => setQuery({ equipment: value }, true)}
            testId="overview-inspect-eq"
          />
          <p className="oracle-sidebar__caption" data-testid="overview-inspect-meta">
            {selectValue || "—"} · chart sample {snap.rowCount} points ·{" "}
            {snap.columns.length} plottable columns
            {snap.span ? ` · ${snap.span}` : ""}
          </p>
          {err ? (
            <InlineAlert id="inspect-err" variant="danger" testId="inspect-err">
              {err}
            </InlineAlert>
          ) : null}
          <PlotlyHost
            id="data-inspect"
            label="Inspection chart"
            figure={snap.figure}
            loading={chartLoad.loading}
            height={Math.min(
              4000,
              Math.max(280, (snap.selected.length || snap.columns.length || 1) * 160),
            )}
            downloadFilename={`${selectValue || "equipment"}_inspect`}
            testId="overview-inspect-plot"
          />
          <Button
            id="dl-inspect"
            label={`Download \`${selectValue || "csv"}\` JSON sample`}
            variant="secondary"
            disabled={!snap.figure?.data?.length}
            onClick={() => {
              const rows = snap.figure?.data?.[0] as
                | { x?: unknown[]; y?: unknown[] }
                | undefined;
              if (!rows?.x?.length) return;
              const preview = rows.x.map((x, i) => ({
                timestamp: x,
                value: rows.y?.[i] ?? null,
              }));
              downloadRowsCsv(`${selectValue || "equipment"}_series.csv`, preview);
            }}
            testId="overview-dl-inspect"
          />
        </section>
      </div>
    </AppShell>
  );
}
