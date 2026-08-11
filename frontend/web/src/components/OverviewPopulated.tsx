import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DataTable,
  Expander,
  InlineAlert,
  Metric,
  Select,
  Button,
  Slider,
  Checkbox,
} from "./widgets";
import { PlotlyHost } from "./widgets/PlotlyHost";
import {
  getFddStatus,
  listFddRules,
  getFddResults,
  runFdd,
} from "../api/fddApi";
import {
  getPackageMapping,
  getSessionConfig,
  putSessionConfig,
  type SessionConfig,
} from "../api/mappingApi";
import { downloadRowsCsv } from "../api/csvDownload";
import type { OverviewVibe19Response } from "../api/overviewTypes";
import { fetchCentralOverview } from "../api/centralOverview";
import { postInspect, type FddEquipmentItem } from "../api/analyticsApi";
import { equipmentInspectionChart } from "../api/inspectChart";
import type { PlotlyFigure } from "../api/plotDataset";
import { RULES_UPDATED_EVENT } from "./RuleTuningPanel";
import { naturalCompare } from "../naturalSort";

const DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

type DaySched = { occupied: boolean; start: string; end: string };

const DEFAULT_WEEK: Record<(typeof DAYS)[number], DaySched> = {
  Monday: { occupied: true, start: "07:00", end: "17:00" },
  Tuesday: { occupied: true, start: "07:00", end: "17:00" },
  Wednesday: { occupied: true, start: "07:00", end: "17:00" },
  Thursday: { occupied: true, start: "07:00", end: "17:00" },
  Friday: { occupied: true, start: "07:00", end: "17:00" },
  Saturday: { occupied: false, start: "07:00", end: "17:00" },
  Sunday: { occupied: false, start: "07:00", end: "17:00" },
};

const PARAMS_KEY = "openfdd.ui.rule_params";
/** v2 defaults: M–F 07:00–17:00 occupied; weekends unoccupied. */
const SCHEDULE_KEY = "openfdd.ui.occupancy_schedule.v2";

function loadStoredParams(): Record<string, Record<string, number>> {
  try {
    const raw = localStorage.getItem(PARAMS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, Record<string, number>>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function loadStoredSchedule(): {
  week: Record<(typeof DAYS)[number], DaySched>;
  tz: string;
} {
  try {
    const raw = localStorage.getItem(SCHEDULE_KEY);
    if (!raw) return { week: DEFAULT_WEEK, tz: "America/Chicago" };
    const parsed = JSON.parse(raw) as {
      week?: Record<string, DaySched>;
      tz?: string;
    };
    const week = { ...DEFAULT_WEEK };
    if (parsed.week && typeof parsed.week === "object") {
      for (const d of DAYS) {
        const s = parsed.week[d];
        if (s && typeof s.start === "string" && typeof s.end === "string") {
          week[d] = {
            occupied: Boolean(s.occupied),
            start: s.start,
            end: s.end,
          };
        }
      }
    }
    return {
      week,
      tz:
        typeof parsed.tz === "string" && parsed.tz.trim()
          ? parsed.tz
          : "America/Chicago",
    };
  } catch {
    return { week: DEFAULT_WEEK, tz: "America/Chicago" };
  }
}

function saveStoredSchedule(
  week: Record<string, DaySched>,
  tz: string,
): void {
  try {
    localStorage.setItem(SCHEDULE_KEY, JSON.stringify({ week, tz }));
  } catch {
    /* ignore */
  }
}

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function hoursPerWeek(week: Record<string, DaySched>): number {
  let h = 0;
  for (const d of DAYS) {
    const s = week[d];
    if (!s?.occupied) continue;
    const [sh, sm] = s.start.split(":").map(Number);
    const [eh, em] = s.end.split(":").map(Number);
    h += Math.max(0, eh + em / 60 - (sh + sm / 60));
  }
  return Math.round(h * 10) / 10;
}

function spanHours(start?: string | null, end?: string | null): number | null {
  if (!start || !end) return null;
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null;
  return Math.round(((b - a) / 3_600_000) * 10) / 10;
}

export interface OverviewPopulatedProps {
  buildingId: string;
  equipment: FddEquipmentItem[];
  equipmentId: string;
  onEquipmentChange: (id: string) => void;
  unitSystem: "imperial" | "metric";
}

/** Vibe Overview — metrics through data inspection (central DataFusion). */
export function OverviewPopulated({
  buildingId,
  equipment,
  equipmentId,
  onEquipmentChange,
  unitSystem,
}: OverviewPopulatedProps) {
  const [ruleCount, setRuleCount] = useState(0);
  const [rowCount, setRowCount] = useState(0);
  const [firstTs, setFirstTs] = useState<string | null>(null);
  const [lastTs, setLastTs] = useState<string | null>(null);
  const [eqKind, setEqKind] = useState("—");
  const [overview, setOverview] = useState<OverviewVibe19Response | null>(null);
  const [overviewErr, setOverviewErr] = useState<string | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [zoneLow, setZoneLow] = useState(70);
  const [zoneHigh, setZoneHigh] = useState(75);
  const [week, setWeek] = useState(() => loadStoredSchedule().week);
  const [tz, setTz] = useState(() => loadStoredSchedule().tz);
  const [schedOpen, setSchedOpen] = useState(true);
  const [motorTableOpen, setMotorTableOpen] = useState(false);
  const [mechBinsOpen, setMechBinsOpen] = useState(false);
  const [mechCoverageOpen, setMechCoverageOpen] = useState(false);
  const [econMetricsOpen, setEconMetricsOpen] = useState(false);
  const [basHistOpen, setBasHistOpen] = useState(false);
  const [econOverlayOpen, setEconOverlayOpen] = useState(false);
  const [econSkippedOpen, setEconSkippedOpen] = useState(false);
  const [econOverlayEq, setEconOverlayEq] = useState("");
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleNote, setScheduleNote] = useState<string | null>(null);
  const [inspectOptions, setInspectOptions] = useState<string[]>([]);
  const [inspectPick, setInspectPick] = useState(equipmentId);
  const [inspectCols, setInspectCols] = useState<string[]>([]);
  const [inspectSelectedCols, setInspectSelectedCols] = useState<string[]>([]);
  const [inspectFig, setInspectFig] = useState<PlotlyFigure | null>(null);
  const [inspectMeta, setInspectMeta] = useState<{
    row_count: number;
    span: string;
  } | null>(null);
  const [inspectBusy, setInspectBusy] = useState(false);
  const [inspectErr, setInspectErr] = useState<string | null>(null);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [rulesBusy, setRulesBusy] = useState(false);
  const [rulesNote, setRulesNote] = useState<string | null>(null);
  const [rulesErr, setRulesErr] = useState<string | null>(null);
  const [lastRuleResultCount, setLastRuleResultCount] = useState<number | null>(
    null,
  );
  const [overviewElapsedSec, setOverviewElapsedSec] = useState(0);
  const overviewLoadStarted = useRef<number | null>(null);
  const inspectReqSeq = useRef(0);

  const selected = equipment.find((e) => e.equipment_id === equipmentId);
  const tempUnit = unitSystem === "metric" ? "°C" : "°F";
  const bareMin = hoursPerWeek(week);
  const spanH =
    overview?.span?.span_hours != null
      ? Math.round(Number(overview.span.span_hours) * 10) / 10
      : spanHours(firstTs, lastTs);

  const devicesByType = useMemo(() => {
    if (overview?.devices_by_type?.length) {
      return overview.devices_by_type.map((r) => ({
        equipment_type: r.type,
        count: r.count,
      }));
    }
    const map = new Map<string, number>();
    for (const e of equipment) {
      const t = String(e.equipment_type || "unknown");
      map.set(t, (map.get(t) ?? 0) + 1);
    }
    return [...map.entries()]
      .map(([equipment_type, count]) => ({ equipment_type, count }))
      .sort((a, b) => a.equipment_type.localeCompare(b.equipment_type));
  }, [equipment, overview?.devices_by_type]);

  const refreshMeta = useCallback(async () => {
    setLoadingMeta(true);
    try {
      const [status, rules] = await Promise.all([
        getFddStatus().catch(() => null),
        listFddRules().catch(() => []),
      ]);
      setRuleCount(status?.rule_count ?? rules.length);
      if (!buildingId) return;
      const map = await getPackageMapping(
        buildingId,
        equipmentId || undefined,
      ).catch(() => null);
      const eq =
        map?.equipment?.find((e) => e.equipment_id === equipmentId) ??
        map?.equipment?.[0];
      setRowCount(eq?.sampling?.row_count ?? 0);
      setFirstTs(eq?.sampling?.first_timestamp ?? null);
      setLastTs(eq?.sampling?.last_timestamp ?? null);
      setEqKind(String(eq?.equipment_type || selected?.equipment_type || "—"));
    } finally {
      setLoadingMeta(false);
    }
  }, [buildingId, equipmentId, selected?.equipment_type]);

  const refreshOverview = useCallback(async () => {
    if (!buildingId) return;
    setLoadingOverview(true);
    setOverviewErr(null);
    try {
      const body = await fetchCentralOverview({
        building_id: buildingId,
        equipment,
        econ_overlay_equipment_id: econOverlayEq || null,
      });
      if (!body.ok) {
        throw new Error(body.error || "Central analytics failed");
      }
      setOverview(body);
      if (body.span?.start) setFirstTs(body.span.start);
      if (body.span?.end) setLastTs(body.span.end);
      setInspectOptions(body.equipment_ids);
      if (!inspectPick && body.equipment_ids[0]) {
        setInspectPick(body.equipment_ids[0]);
      }
      const results = await getFddResults(buildingId).catch(() => null);
      if (results) setLastRuleResultCount(results.length);
    } catch (err) {
      setOverviewErr(formatErr(err));
      setOverview(null);
    } finally {
      setLoadingOverview(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingId, equipment, econOverlayEq]);

  const refreshInspect = useCallback(
    async (opts?: { pick?: string; cols?: string[]; resetCols?: boolean }) => {
      const pick = opts?.pick ?? inspectPick;
      const resetCols = Boolean(opts?.resetCols);
      const selectedCols = resetCols
        ? []
        : (opts?.cols ?? inspectSelectedCols);
      if (!buildingId || !pick || pick === "(weather)") return;
      const seq = ++inspectReqSeq.current;
      setInspectBusy(true);
      setInspectErr(null);
      try {
        const env = await postInspect({
          building_id: buildingId,
          equipment_ids: [pick],
          max_points: 2000,
          series: {
            columns: selectedCols.length > 0 ? selectedCols : undefined,
          },
        });
        if (seq !== inspectReqSeq.current) return;
        const cov = (env.coverage ?? {}) as Record<string, unknown>;
        const plottable = Array.isArray(cov.plottable_columns)
          ? (cov.plottable_columns as string[])
          : [];
        const plotted = Array.isArray(cov.columns_plotted)
          ? (cov.columns_plotted as string[])
          : [];
        setInspectCols(plottable.length ? plottable : plotted);
        // Only update selection when contents change — a fresh array every time
        // re-triggers this callback (inspectSelectedCols dep) and flashes Plotly.
        setInspectSelectedCols((prev) => {
          if (resetCols || opts?.cols !== undefined) {
            if (resetCols || selectedCols.length === 0) {
              return plotted;
            }
            return selectedCols;
          }
          if (prev.length) {
            const next = prev.filter(
              (c) => plottable.includes(c) || plotted.includes(c),
            );
            if (
              next.length === prev.length &&
              next.every((c, i) => c === prev[i])
            ) {
              return prev;
            }
            return next.length ? next : plotted;
          }
          return plotted;
        });
        const rowCountN = Number(cov.row_count ?? env.points?.length ?? 0);
        if (Number.isFinite(rowCountN)) setRowCount(rowCountN);
        const first =
          cov.first_timestamp != null ? String(cov.first_timestamp) : null;
        const last =
          cov.last_timestamp != null ? String(cov.last_timestamp) : null;
        if (first) setFirstTs(first);
        if (last) setLastTs(last);
        setInspectMeta({
          row_count: rowCountN,
          span: first && last ? `${first} → ${last}` : "—",
        });
        if (env.warnings?.length && !env.points?.length) {
          setInspectFig(null);
          setInspectErr(env.warnings[0] ?? "Inspection unavailable");
          return;
        }
        const colsForChart = (
          resetCols || selectedCols.length === 0 ? plotted : selectedCols
        ).filter(
          (c) =>
            plottable.includes(c) || plotted.includes(c) || !plottable.length,
        );
        const fig = equipmentInspectionChart(env.points ?? [], {
          equipmentId: pick,
          columns: colsForChart.length ? colsForChart : plotted,
        });
        setInspectFig(fig);
        setInspectErr(
          fig
            ? null
            : "No plottable numeric columns for this equipment in historian Parquet.",
        );
      } catch (err) {
        if (seq !== inspectReqSeq.current) return;
        setInspectErr(formatErr(err));
        setInspectFig(null);
      } finally {
        if (seq === inspectReqSeq.current) setInspectBusy(false);
      }
    },
    [buildingId, inspectPick, inspectSelectedCols],
  );

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  // Clear building analytics only when the site changes. Overlay AHU must
  // not wipe motor / cooling / inspect — it only swaps overlay traces.
  useEffect(() => {
    inspectReqSeq.current += 1;
    setOverview(null);
    setOverviewErr(null);
    setInspectFig(null);
    setInspectErr(null);
    setInspectCols([]);
    setInspectSelectedCols([]);
    setInspectMeta(null);
    setInspectPick("");
    setInspectBusy(false);
  }, [buildingId]);

  useEffect(() => {
    if (!econOverlayEq || !overview) return;
    void refreshOverview();
    // refreshOverview identity already tracks econOverlayEq.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [econOverlayEq]);

  // Top equipment drives inspect: remount + all plottable columns.
  useEffect(() => {
    if (!buildingId || !equipmentId) return;
    setInspectPick(equipmentId);
    setInspectBusy(true);
    void refreshInspect({ pick: equipmentId, resetCols: true });
    // Intentionally omit refreshInspect — resetCols ignores selected cols.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingId, equipmentId]);

  useEffect(() => {
    void getSessionConfig()
      .then((body) => {
        const p = body.config?.params ?? {};
        const vav = p["VAV-1"] ?? {};
        if (typeof vav.zone_low === "number") setZoneLow(vav.zone_low);
        if (typeof vav.zone_high === "number") setZoneHigh(vav.zone_high);
      })
      .catch(() => undefined);
  }, [buildingId]);

  useEffect(() => {
    const onRules = (ev: Event) => {
      const detail = (ev as CustomEvent).detail as {
        mode?: string;
        rule_id?: string;
        count?: number;
      };
      const n = detail?.count;
      if (typeof n === "number") setLastRuleResultCount(n);
      setRulesNote(
        detail?.mode === "single"
          ? `Rule ${detail.rule_id} updated · ${n ?? "—"} result row(s)`
          : `Rules updated · ${n ?? "—"} result row(s)`,
      );
      void getFddResults(buildingId)
        .then((rows) => setLastRuleResultCount(rows.length))
        .catch(() => undefined);
    };
    window.addEventListener(RULES_UPDATED_EVENT, onRules);
    return () => window.removeEventListener(RULES_UPDATED_EVENT, onRules);
  }, [buildingId]);

  const saveSchedule = async () => {
    setScheduleBusy(true);
    setScheduleNote(null);
    try {
      saveStoredSchedule(week, tz);
      const prev = await getSessionConfig().catch(() => null);
      const dayKey: Record<string, string> = {
        Monday: "mon",
        Tuesday: "tue",
        Wednesday: "wed",
        Thursday: "thu",
        Friday: "fri",
        Saturday: "sat",
        Sunday: "sun",
      };
      const days: Record<string, DaySched> = {};
      for (const d of DAYS) {
        days[dayKey[d] ?? d.toLowerCase().slice(0, 3)] = week[d];
      }
      const occupancy_schedule = {
        timezone: tz,
        nominal_occ_hours_week: bareMin,
        days,
      };
      const config: SessionConfig = {
        ...(prev?.config ?? {}),
        schema_version: prev?.config?.schema_version ?? "openfdd.session.v1",
        unit_system: unitSystem,
        occupancy_schedule,
        params: {
          ...(prev?.config?.params ?? {}),
          "VAV-1": {
            ...(prev?.config?.params?.["VAV-1"] ?? {}),
            zone_low: zoneLow,
            zone_high: zoneHigh,
          },
          "SCHED-1": {
            ...(prev?.config?.params?.["SCHED-1"] ?? {}),
            bare_min_occ_hours_week: bareMin,
          },
        },
      };
      await putSessionConfig(config);
      setScheduleNote(
        `Schedule saved (tz ${tz}, ${bareMin} occ h/wk). Calendar persisted to session config.`,
      );
      void refreshOverview();
    } catch (err) {
      setScheduleNote(formatErr(err));
    } finally {
      setScheduleBusy(false);
    }
  };

  const onUpdateAllRules = async () => {
    if (!buildingId) {
      setRulesErr("Select an active site first");
      return;
    }
    setRulesBusy(true);
    setRulesErr(null);
    setRulesNote("Running all rules with tuned params…");
    try {
      const params = loadStoredParams();
      const prev = await getSessionConfig().catch(() => null);
      await putSessionConfig({
        ...(prev?.config ?? {}),
        schema_version: prev?.config?.schema_version ?? "openfdd.session.v1",
        params: { ...(prev?.config?.params ?? {}), ...params },
      });
      const result = await runFdd({
        mode: "registry",
        building_id: buildingId,
        params,
      });
      const n = result.results?.length ?? 0;
      setLastRuleResultCount(n);
      setRulesNote(
        `Ran all rules · ${n} result row(s) · ${String(result.total_ms ?? "—")} ms`,
      );
      try {
        window.dispatchEvent(
          new CustomEvent(RULES_UPDATED_EVENT, {
            detail: { mode: "all", building_id: buildingId, count: n },
          }),
        );
      } catch {
        /* ignore */
      }
    } catch (err) {
      setRulesErr(formatErr(err));
      setRulesNote(null);
    } finally {
      setRulesBusy(false);
    }
  };

  const busy = loadingOverview || loadingMeta;
  const datasetStart = overview?.span?.start ?? firstTs ?? "—";
  const datasetEnd = overview?.span?.end ?? lastTs ?? "—";

  useEffect(() => {
    if (!busy) {
      overviewLoadStarted.current = null;
      return;
    }
    if (overviewLoadStarted.current == null) {
      overviewLoadStarted.current = Date.now();
      setOverviewElapsedSec(0);
    }
    const id = window.setInterval(() => {
      if (overviewLoadStarted.current != null) {
        setOverviewElapsedSec(
          Math.max(
            0,
            Math.round((Date.now() - overviewLoadStarted.current) / 1000),
          ),
        );
      }
    }, 250);
    return () => window.clearInterval(id);
  }, [busy]);

  const chartCount = (() => {
    if (!overview) return 0;
    let n = 0;
    for (const p of overview.motor_weekly.plants) {
      if (p.figure?.data?.length) n += 1;
    }
    if (overview.mech_cooling.figure?.data?.length) n += 1;
    if (overview.economizer_free_cooling.delta_scatter?.data?.length) n += 1;
    if (overview.economizer_free_cooling.mat_residual?.data?.length) n += 1;
    if (overview.economizer_free_cooling.temps_overlay?.data?.length) n += 1;
    if (overview.bas_vs_web_oat.overlay?.data?.length) n += 1;
    if (overview.bas_vs_web_oat.histogram?.data?.length) n += 1;
    if (inspectFig?.data?.length) n += 1;
    return n;
  })();

  return (
    <div
      className={`overview-populated${busy ? " overview-populated--busy" : ""}`}
      data-testid="overview-populated"
      aria-busy={busy || undefined}
    >
      <p className="oracle-sidebar__caption">
        Overview analytics from central DataFusion. Charts are drawn in the browser
        from typed envelopes.
      </p>

      {busy ? (
        <div
          className="overview-busy-panel"
          data-testid="overview-busy"
          role="status"
          aria-live="polite"
        >
          <span className="spinner" aria-hidden />
          <div>
            <strong>
              Updating analytics for <code>{buildingId}</code>
            </strong>
            <p>
              Runtime · mechanical cooling · economizer · schedule via
              DataFusion. Elapsed: <strong>{overviewElapsedSec}s</strong>
            </p>
          </div>
        </div>
      ) : null}

      {!busy && overview ? (
        <InlineAlert
          id="overview-charts-ready"
          variant="info"
          testId="overview-charts-ready"
        >
          Charts ready: <strong>{chartCount}</strong> Plotly figure
          {chartCount === 1 ? "" : "s"} for <code>{buildingId}</code> (
          {overview.elapsed_s}s · {overview.source}). Each plot shows “rendered”
          when Plotly finishes drawing.
        </InlineAlert>
      ) : null}

      <div className="overview-toolbar" data-testid="overview-actions">
        <div className="overview-toolbar__action">
          <Button
            id="overview-update-analytics"
            label={
              busy
                ? `Updating analytics… ${overviewElapsedSec}s`
                : "Update analytics"
            }
            loading={busy}
            onClick={() => {
              void refreshMeta();
              void refreshOverview();
              void refreshInspect();
            }}
            testId="overview-refresh"
          />
          <p className="oracle-sidebar__caption">
            Building charts (all AHUs) — run once after load
          </p>
        </div>
        <div className="overview-toolbar__action">
          <Button
            id="overview-run-all-rules"
            label={rulesBusy ? "Running all rules…" : "Run all rules"}
            loading={rulesBusy}
            onClick={() => void onUpdateAllRules()}
            testId="overview-update-all-rules"
          />
          <p className="oracle-sidebar__caption">
            DataFusion FDD registry → Results / FDD Plots
          </p>
        </div>
        {overview ? (
          <span className="oracle-sidebar__caption">
            {overview.elapsed_s}s · {overview.equipment_count} equip ·{" "}
            {overview.source}
          </span>
        ) : (
          <span className="oracle-sidebar__caption" data-testid="overview-idle-hint">
            Building charts need Update analytics once. Data inspection
            auto-loads every column for the selected equipment.
          </span>
        )}
      </div>

      {overviewErr ? (
        <InlineAlert id="overview-err" variant="danger" testId="overview-err">
          Central analytics unavailable: {overviewErr}. Confirm the package for{" "}
          <code>{buildingId}</code> is loaded and central is healthy.
        </InlineAlert>
      ) : null}

      <p className="oracle-sidebar__caption" data-testid="overview-dual-catalog">
        <strong>Update analytics</strong> draws building-wide motor / economizer
        / OAT charts (both AHUs). <strong>Data inspection</strong> auto-loads
        every plottable column for the selected equipment.{" "}
        <strong>Run all rules</strong> runs the FDD SQL registry. Sidebar{" "}
        <strong>Update this rule</strong> re-runs one rule.
      </p>

      <div className="form-row">
        <Select
          id="overview-equipment-select"
          label="Equipment"
          value={equipmentId}
          options={[...equipment]
            .map((e) => String(e.equipment_id))
            .sort(naturalCompare)
            .map((id) => ({ value: id, label: id }))}
          onChange={onEquipmentChange}
          testId="overview-equipment-select"
        />
      </div>

      <div className="overview-metrics" data-testid="overview-metrics">
        <Metric
          id="ov-eq"
          label="Equipment"
          value={String(overview?.equipment_count ?? equipment.length)}
          testId="overview-eq-count"
        />
        <Metric id="ov-rules" label="Rules" value={String(ruleCount)} testId="overview-rule-count" />
        <Metric id="ov-rows" label="Rows (selected)" value={String(rowCount)} testId="overview-row-count" />
        <Metric id="ov-poll" label="Poll (s)" value="300" testId="overview-poll" />
        <Metric id="ov-kind" label="Kind" value={eqKind} testId="overview-kind" />
      </div>
      <p className="oracle-sidebar__caption" data-testid="overview-source-caption">
        zip:{buildingId}
      </p>
      <div className="overview-metrics overview-metrics--span">
        <Metric id="ov-start" label="Dataset start" value={datasetStart} testId="overview-start" />
        <Metric id="ov-end" label="Dataset end" value={datasetEnd} testId="overview-end" />
        <Metric
          id="ov-span"
          label="Span (h)"
          value={spanH != null ? String(spanH) : "—"}
          testId="overview-span"
        />
      </div>

      <section
        className="overview-section overview-rule-run"
        data-testid="overview-update-rules"
      >
        <h3>Rule run status</h3>
        <p className="oracle-sidebar__caption">
          Tune thresholds with the left-rail sliders. Use{" "}
          <strong>Update this rule</strong> next to a modified slider, or{" "}
          <strong>Run all rules</strong> above for the full registry.
        </p>
        {rulesNote ? (
          <p className="oracle-sidebar__ok" data-testid="overview-rules-note">
            {rulesNote}
          </p>
        ) : null}
        {rulesErr ? (
          <InlineAlert
            id="overview-rules-err"
            variant="danger"
            testId="overview-rules-err"
          >
            {rulesErr}
          </InlineAlert>
        ) : null}
        {lastRuleResultCount != null ? (
          <Metric
            id="ov-rule-results"
            label="Latest FDD result rows"
            value={String(lastRuleResultCount)}
            testId="overview-rule-result-count"
          />
        ) : null}
      </section>

      <section className="overview-section" data-testid="overview-schedule">
        <h3>Building schedule &amp; zone comfort (FDD starting point)</h3>
        <p className="oracle-sidebar__caption">
          Occupancy calendar always drives SCHED-1 (<code>occ_mode</code>) —
          edit times below; do not remove this UI. Zone low/high seed VAV-1
          comfort band. Bare-min hours draw on the air-side motor chart.
        </p>
        <Slider
          id="zone-low"
          label={`Zone low ${tempUnit}`}
          min={55}
          max={72}
          step={0.5}
          value={zoneLow}
          onChange={setZoneLow}
          testId="overview-zone-low"
        />
        <Slider
          id="zone-high"
          label={`Zone high ${tempUnit}`}
          min={70}
          max={85}
          step={0.5}
          value={zoneHigh}
          onChange={setZoneHigh}
          testId="overview-zone-high"
        />
        <Metric
          id="bare-min"
          label="Bare-min occ hours / week"
          value={String(bareMin)}
          testId="overview-bare-min"
        />
        <Expander
          id="edit-weekly-occ"
          label="Edit weekly occupancy (time pickers)"
          expanded={schedOpen}
          onChange={setSchedOpen}
          testId="overview-weekly-occ"
        >
          <label className="oracle-sidebar__field">
            <span className="oracle-sidebar__label">Timezone</span>
            <input
              className="oracle-sidebar__control"
              value={tz}
              onChange={(e) => setTz(e.target.value)}
              data-testid="overview-timezone"
            />
          </label>
          {DAYS.map((day) => (
            <div key={day} className="overview-day" data-testid={`overview-day-${day}`}>
              <strong>{day}</strong>
              <Checkbox
                id={`occ-${day}`}
                label="Occupied"
                checked={week[day].occupied}
                onChange={(checked) =>
                  setWeek((w) => ({
                    ...w,
                    [day]: { ...w[day], occupied: checked },
                  }))
                }
              />
              <label>
                Start{" "}
                <input
                  type="time"
                  value={week[day].start}
                  onChange={(e) =>
                    setWeek((w) => ({
                      ...w,
                      [day]: { ...w[day], start: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                End{" "}
                <input
                  type="time"
                  value={week[day].end}
                  onChange={(e) =>
                    setWeek((w) => ({
                      ...w,
                      [day]: { ...w[day], end: e.target.value },
                    }))
                  }
                />
              </label>
            </div>
          ))}
          <Button
            id="save-schedule"
            label="Save schedule to session config"
            loading={scheduleBusy}
            onClick={() => void saveSchedule()}
            testId="overview-save-schedule"
          />
          {scheduleNote ? (
            <p className="oracle-sidebar__ok" data-testid="overview-schedule-note">
              {scheduleNote}
            </p>
          ) : null}
        </Expander>
      </section>

      <section className="overview-section" data-testid="overview-motor-runtime">
        <h3>Motor / equipment run hours</h3>
        <p className="oracle-sidebar__caption">
          {overview?.motor_weekly.caption ??
            "Bars = run hours by equipment (DataFusion historian)."}
        </p>
        {(overview?.motor_weekly.plants ?? []).map((plant) => (
          <div key={plant.plant_group} data-testid={`overview-motor-${plant.plant_group}`}>
            <h4>{plant.title}</h4>
            {plant.empty || !plant.figure ? (
              <p className="oracle-sidebar__caption">
                No series for {plant.title.split("—")[0]?.trim().toLowerCase()}.
              </p>
            ) : (
              <PlotlyHost
                id={`motor-weekly-${plant.plant_group}`}
                label={plant.title}
                figure={plant.figure}
                loading={loadingOverview}
                height={340}
                testId={`overview-motor-${plant.plant_group}-plot`}
              />
            )}
          </div>
        ))}
        {!overview && !loadingOverview ? (
          <p className="oracle-sidebar__caption">No motor charts yet.</p>
        ) : null}
        <Expander
          id="weekly-motor-table"
          label="Weekly motor hours table"
          expanded={motorTableOpen}
          onChange={setMotorTableOpen}
          testId="overview-motor-table-exp"
        >
          {overview?.motor_weekly.table?.length ? (
            <DataTable
              id="motor-weekly-table"
              label="Weekly motor hours"
              columns={Object.keys(overview.motor_weekly.table[0] ?? {}).map((k) => ({
                key: k,
                header: k,
              }))}
              rows={
                overview.motor_weekly.table.slice(0, 200) as Array<
                  Record<string, string | number>
                >
              }
              testId="overview-motor-table"
            />
          ) : (
            <p className="oracle-sidebar__caption">No runtime rows.</p>
          )}
        </Expander>
      </section>

      <section className="overview-section" data-testid="overview-mech-cooling">
        <h3>Mechanical cooling hours by OAT bin</h3>
        <p className="oracle-sidebar__caption">
          {overview?.mech_cooling.caption ??
            "Chillers / DX / VRF compressor-proof; never CHW valves."}
        </p>
        {overview?.mech_cooling.callout ? (
          <p
            className="oracle-sidebar__caption"
            data-testid="overview-mech-callout"
            style={{
              background: "rgba(59, 130, 246, 0.12)",
              borderRadius: 8,
              padding: "10px 12px",
            }}
          >
            {overview.mech_cooling.callout}
          </p>
        ) : null}
        <PlotlyHost
          id="mech-cooling"
          label="Mechanical cooling by OAT"
          figure={overview?.mech_cooling.figure ?? null}
          loading={loadingOverview}
          height={360}
          testId="overview-mech-plot"
        />
        {overview?.mech_cooling.bins?.length ? (
          <Expander
            id="mech-bins-exp"
            label="Mech cooling OAT bins table"
            expanded={mechBinsOpen}
            onChange={setMechBinsOpen}
            testId="overview-mech-bins-exp"
          >
            <DataTable
              id="mech-bins"
              label="Mech cooling OAT bins"
              columns={Object.keys(overview.mech_cooling.bins[0] ?? {}).map((k) => ({
                key: k,
                header: k,
              }))}
              rows={
                overview.mech_cooling.bins.slice(0, 80) as Array<
                  Record<string, string | number>
                >
              }
              testId="overview-mech-bins"
            />
            <Button
              id="dl-mech-bins"
              label="Download mech cooling OAT bins CSV"
              variant="secondary"
              onClick={() =>
                downloadRowsCsv(
                  "mech_cooling_oat_bins.csv",
                  overview.mech_cooling.bins,
                )
              }
              testId="overview-dl-mech-bins"
            />
          </Expander>
        ) : null}
        {overview?.mech_cooling.coverage?.length ? (
          <Expander
            id="mech-coverage-exp"
            label={`Mechanical cooling devices${
              overview.mech_cooling.n_included != null
                ? ` — ${overview.mech_cooling.n_included} included, ${overview.mech_cooling.n_excluded ?? 0} excluded`
                : ""
            }`}
            expanded={mechCoverageOpen}
            onChange={setMechCoverageOpen}
            testId="overview-mech-coverage-exp"
          >
            <DataTable
              id="mech-coverage"
              label="Cooling coverage"
              columns={Object.keys(overview.mech_cooling.coverage[0] ?? {}).map(
                (k) => ({ key: k, header: k }),
              )}
              rows={
                overview.mech_cooling.coverage.slice(0, 80) as Array<
                  Record<string, string | number>
                >
              }
              testId="overview-mech-coverage"
            />
            <Button
              id="dl-mech-cov"
              label="Download cooling coverage CSV"
              variant="secondary"
              onClick={() =>
                downloadRowsCsv(
                  "mech_cooling_coverage.csv",
                  overview.mech_cooling.coverage,
                )
              }
              testId="overview-dl-mech-cov"
            />
          </Expander>
        ) : null}
      </section>

      <section className="overview-section" data-testid="overview-economizer">
        <h3>Economizer weather opportunity / compliance</h3>
        <p className="oracle-sidebar__caption">
          {overview?.economizer_weather.caption ??
            "Strict web dry-bulb + dewpoint opportunity hours."}
        </p>
        {overview?.economizer_weather.table?.length ? (
          <>
            <DataTable
              id="econ-table"
              label="Economizer weather summary"
              columns={Object.keys(overview.economizer_weather.table[0] ?? {}).map(
                (k) => ({ key: k, header: k }),
              )}
              rows={
                overview.economizer_weather.table as Array<
                  Record<string, string | number>
                >
              }
              testId="overview-econ-table"
            />
            <Button
              id="dl-econ-weather"
              label="Download economizer weather CSV"
              variant="secondary"
              onClick={() =>
                downloadRowsCsv(
                  "economizer_weather.csv",
                  overview.economizer_weather.table,
                )
              }
              testId="overview-dl-econ-weather"
            />
          </>
        ) : (
          <p className="oracle-sidebar__caption">
            {loadingOverview
              ? "Loading economizer…"
              : "No AHU/chiller/heat-pump rows with web weather or applicable signals."}
          </p>
        )}
      </section>

      <section className="overview-section" data-testid="overview-econ-free-cooling">
        <h3>Economizer free-cooling diagnostics (fan on)</h3>
        <p className="oracle-sidebar__caption">
          {overview?.economizer_free_cooling.caption ??
            "G36 mixing plots while supply fan is running."}
        </p>
        {overview?.economizer_free_cooling.metrics?.length ? (
          <Expander
            id="econ-metrics-exp"
            label="Economizer free-cooling diagnostics table"
            expanded={econMetricsOpen}
            onChange={setEconMetricsOpen}
            testId="overview-econ-metrics-exp"
          >
            <DataTable
              id="econ-metrics"
              label="Economizer diagnostic metrics"
              columns={Object.keys(
                overview.economizer_free_cooling.metrics[0] ?? {},
              ).map((k) => ({ key: k, header: k }))}
              rows={
                overview.economizer_free_cooling.metrics as Array<
                  Record<string, string | number>
                >
              }
              testId="overview-econ-metrics"
            />
            <Button
              id="dl-econ-metrics"
              label="Download economizer diagnostic metrics CSV"
              variant="secondary"
              onClick={() =>
                downloadRowsCsv(
                  "economizer_free_cooling_metrics.csv",
                  overview.economizer_free_cooling.metrics,
                )
              }
              testId="overview-dl-econ-metrics"
            />
          </Expander>
        ) : null}
        <PlotlyHost
          id="econ-delta"
          label="Economizer free-cooling delta scatter"
          figure={overview?.economizer_free_cooling.delta_scatter ?? null}
          loading={loadingOverview}
          height={380}
          testId="overview-econ-delta-plot"
        />
        {!overview?.economizer_free_cooling.delta_scatter && !loadingOverview ? (
          <p className="oracle-sidebar__caption">
            Need AHU/RTU with fan-status (or fan-cmd) on, plus OAT, RAT, and MAT
            with enough |OAT−RAT|≥10°F samples for the delta scatter.
          </p>
        ) : null}
        <PlotlyHost
          id="econ-mat-resid"
          label="MAT residual"
          figure={overview?.economizer_free_cooling.mat_residual ?? null}
          loading={loadingOverview}
          height={320}
          testId="overview-econ-mat-resid-plot"
        />
        <p className="oracle-sidebar__caption">
          MAT residual is measured mixed-air temp minus the ideal mixing-box
          prediction from RAT, OAT, and OA damper % (fan on, identifiable
          samples) — near zero means the mixing model matches; large bias
          suggests sensor, damper, or leakage issues.
        </p>
        <Expander
          id="econ-temps-overlay"
          label="Free-cooling temps + OA damper overlay"
          expanded={econOverlayOpen}
          onChange={setEconOverlayOpen}
          testId="overview-econ-overlay-exp"
        >
          {overview?.economizer_free_cooling.metrics?.length ? (
            <Select
              id="econ-overlay-eq"
              label="AHU for overlay"
              value={
                econOverlayEq ||
                overview.economizer_free_cooling.overlay_equipment_id ||
                ""
              }
              options={overview.economizer_free_cooling.metrics.map((m) => ({
                value: String(m.equipment_id),
                label: String(m.equipment_id),
              }))}
              onChange={(v) => {
                setEconOverlayEq(v);
              }}
              testId="overview-econ-overlay-eq"
            />
          ) : null}
          <PlotlyHost
            id="econ-temps"
            label="Free-cooling temps + OA damper"
            figure={overview?.economizer_free_cooling.temps_overlay ?? null}
            loading={loadingOverview}
            height={360}
            testId="overview-econ-temps-plot"
          />
        </Expander>
        {(overview?.economizer_free_cooling.skipped?.length ?? 0) > 0 ? (
          <Expander
            id="econ-skipped"
            label={`Skipped units (${overview!.economizer_free_cooling.skipped.length})`}
            expanded={econSkippedOpen}
            onChange={setEconSkippedOpen}
            testId="overview-econ-skipped-exp"
          >
            <DataTable
              id="econ-skipped"
              label="Skipped units"
              columns={[
                { key: "equipment_id", header: "equipment_id" },
                { key: "reason", header: "reason" },
              ]}
              rows={
                overview!.economizer_free_cooling.skipped as Array<
                  Record<string, string | number>
                >
              }
              testId="overview-econ-skipped"
            />
          </Expander>
        ) : null}
      </section>

      <section className="overview-section" data-testid="overview-bas-web-oat">
        <h3>BAS vs web outdoor-air temperature</h3>
        <p className="oracle-sidebar__caption">
          {overview?.bas_vs_web_oat.caption ??
            "Overlay of BAS OAT and web dry-bulb with ±oat_err band."}
        </p>
        {!overview?.bas_vs_web_oat.overlay && !loadingOverview ? (
          <InlineAlert id="bas-web-need" variant="info">
            Need both BAS outdoor-air temp and web weather OAT for the overlay
            chart.
          </InlineAlert>
        ) : (
          <PlotlyHost
            id="bas-web-overlay"
            label="BAS vs web OAT"
            figure={overview?.bas_vs_web_oat.overlay ?? null}
            loading={loadingOverview}
            height={360}
            testId="overview-bas-overlay-plot"
          />
        )}
        <Expander
          id="bas-web-hist"
          label="BAS − web OAT deviation histogram"
          expanded={basHistOpen}
          onChange={setBasHistOpen}
          testId="overview-bas-hist-exp"
        >
          <PlotlyHost
            id="bas-web-hist"
            label="BAS − web deviation"
            figure={overview?.bas_vs_web_oat.histogram ?? null}
            loading={loadingOverview}
            height={300}
            testId="overview-bas-hist-plot"
          />
        </Expander>
      </section>

      <p className="oracle-sidebar__caption">
        Tune thresholds in the left sidebar → <strong>Update this rule</strong>{" "}
        / Overview <strong>Run all rules</strong> → browse FDD Plots by device
        type.
      </p>

      <section className="overview-section" data-testid="overview-devices-by-type">
        <h3>Devices by type</h3>
        <DataTable
          id="devices-by-type"
          label="Devices by type"
          columns={[
            { key: "equipment_type", header: "type" },
            { key: "count", header: "count" },
          ]}
          rows={devicesByType}
          testId="overview-devices-table"
        />
      </section>

      <section className="overview-section" data-testid="overview-data-inspection">
        <h3>Data inspection — raw CSV</h3>
        <p className="oracle-sidebar__caption">
          Pick any uploaded equipment (or weather) CSV and plot numeric / status
          columns as stacked Plotly line charts.
        </p>
        <Select
          id="inspect-eq"
          label="CSV / equipment"
          value={inspectPick}
          options={(inspectOptions.length
            ? inspectOptions
            : equipment.map((e) => String(e.equipment_id))
          ).map((id) => ({ value: id, label: id }))}
          onChange={(v) => {
            setInspectPick(v);
            if (v !== "(weather)") {
              onEquipmentChange(v);
              return;
            }
            setInspectBusy(true);
            void refreshInspect({ pick: v, resetCols: true });
          }}
          testId="overview-inspect-eq"
        />
        {inspectCols.length ? (
          <label className="oracle-sidebar__field">
            <span className="oracle-sidebar__label">
              Columns to plot (default: all) — click to toggle
            </span>
            <select
              className="oracle-sidebar__control"
              multiple
              size={Math.min(8, inspectCols.length)}
              value={inspectSelectedCols}
              onChange={(e) => {
                const opts = [...e.target.selectedOptions].map((o) => o.value);
                setInspectSelectedCols(opts);
                void refreshInspect({ cols: opts });
              }}
              data-testid="overview-inspect-cols-select"
            >
              {inspectCols.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <p className="oracle-sidebar__caption" data-testid="overview-inspect-meta">
          {inspectPick || "—"} · {inspectMeta?.row_count ?? rowCount} rows ·{" "}
          {inspectSelectedCols.length || inspectCols.length} /{" "}
          {inspectCols.length} plottable columns
          {inspectMeta?.span ? ` · ${inspectMeta.span}` : ""}
        </p>
        {inspectErr ? (
          <InlineAlert id="inspect-err" variant="danger">
            {inspectErr}
          </InlineAlert>
        ) : null}
        {!inspectSelectedCols.length && inspectCols.length ? (
          <InlineAlert id="inspect-pick-cols" variant="info">
            Select at least one column to plot.
          </InlineAlert>
        ) : null}
        <PlotlyHost
          key={`overview-inspect-${inspectPick || "none"}`}
          id="data-inspect"
          figureId={`overview-inspect-${inspectPick || "none"}`}
          label="Inspection chart"
          figure={inspectFig}
          loading={inspectBusy}
          height={Math.min(
            4000,
            Math.max(280, (inspectSelectedCols.length || 1) * 160),
          )}
          testId="overview-inspect-plot"
        />
        <Button
          id="dl-inspect"
          label={`Download \`${inspectPick || "csv"}\` JSON sample`}
          variant="secondary"
          disabled={!inspectFig?.data?.length}
          onClick={() => {
            const rows =
              (inspectFig?.data?.[0] as { x?: unknown[]; y?: unknown[] } | undefined);
            if (!rows?.x?.length) return;
            const preview = rows.x.map((x, i) => ({
              timestamp: x,
              value: rows.y?.[i] ?? null,
            }));
            downloadRowsCsv(`${inspectPick || "equipment"}_series.csv`, preview);
          }}
          testId="overview-dl-inspect"
        />
      </section>
    </div>
  );
}
