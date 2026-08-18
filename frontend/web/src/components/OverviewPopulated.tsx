import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DataTable,
  Expander,
  InlineAlert,
  Metric,
  Button,
  Slider,
  Checkbox,
} from "./widgets";
import { SectionTabs } from "./SectionTabs";
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
import type { FddEquipmentItem } from "../api/analyticsApi";
import { VavHealthSection } from "./VavHealthSection";
import { PlantHealthSections } from "./PlantHealthSections";
import { RULES_UPDATED_EVENT } from "./RuleTuningPanel";
import { naturalCompare } from "../lib/naturalSort";
import {
  cookbookKind,
  cookbookRuleCount,
  datasetTimeSpan,
  formatOverviewTs,
  isWeatherEquipmentId,
  spanHoursBetween,
} from "../lib/overviewMetrics";
import {
  effectiveRunParams,
  loadLocalRuleParams,
  SESSION_SCHEMA,
} from "../lib/ruleParams";

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

/** v2 defaults: M–F 07:00–17:00 occupied; weekends unoccupied. */
const SCHEDULE_KEY = "openfdd.ui.occupancy_schedule.v2";

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

export interface OverviewPopulatedProps {
  buildingId: string;
  equipment: FddEquipmentItem[];
  equipmentId: string;
  onEquipmentChange: (id: string) => void;
  unitSystem: "imperial" | "metric";
}

/** Vibe Overview — metrics, tables, and plant health matrices (central DataFusion). */
export function OverviewPopulated({
  buildingId,
  equipment,
  equipmentId,
  onEquipmentChange: _onEquipmentChange,
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
  const [vavHealthToken, setVavHealthToken] = useState(0);
  const [zoneLow, setZoneLow] = useState(70);
  const [zoneHigh, setZoneHigh] = useState(75);
  const [week, setWeek] = useState(() => loadStoredSchedule().week);
  const [tz, setTz] = useState(() => loadStoredSchedule().tz);
  const [schedOpen, setSchedOpen] = useState(true);
  const [motorTableOpen, setMotorTableOpen] = useState(true);
  const [mechBinsOpen, setMechBinsOpen] = useState(true);
  const [mechCoverageOpen, setMechCoverageOpen] = useState(true);
  const [econMetricsOpen, setEconMetricsOpen] = useState(true);
  const [econSkippedOpen, setEconSkippedOpen] = useState(true);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleNote, setScheduleNote] = useState<string | null>(null);
  const [rulesBusy, setRulesBusy] = useState(false);
  const [rulesNote, setRulesNote] = useState<string | null>(null);
  const [rulesErr, setRulesErr] = useState<string | null>(null);
  const [lastRuleResultCount, setLastRuleResultCount] = useState<number | null>(
    null,
  );
  const [overviewElapsedSec, setOverviewElapsedSec] = useState(0);
  const overviewLoadStarted = useRef<number | null>(null);
  const hasOverview = useRef(false);
  const lastBuildingId = useRef(buildingId);

  const sortedEquipment = useMemo(
    () =>
      [...equipment].sort((a, b) =>
        naturalCompare(String(a.equipment_id), String(b.equipment_id)),
      ),
    [equipment],
  );
  const selected =
    sortedEquipment.find((e) => e.equipment_id === equipmentId) ??
    sortedEquipment[0];
  const tempUnit = unitSystem === "metric" ? "°C" : "°F";
  const bareMin = hoursPerWeek(week);
  const spanH =
    overview?.span?.span_hours != null
      ? Math.round(Number(overview.span.span_hours) * 10) / 10
      : spanHoursBetween(firstTs, lastTs);

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
    try {
      const [status, rules] = await Promise.all([
        getFddStatus().catch(() => null),
        listFddRules().catch(() => []),
      ]);
      setRuleCount(cookbookRuleCount(rules, status?.rule_count));
      if (!buildingId) return;
      const map = await getPackageMapping(buildingId).catch(() => null);
      const frames = map?.equipment ?? [];
      const span = datasetTimeSpan(frames);
      setFirstTs(span.start);
      setLastTs(span.end);
      const eq =
        frames.find(
          (e) =>
            e.equipment_id === equipmentId &&
            !isWeatherEquipmentId(String(e.equipment_id)),
        ) ??
        frames.find((e) => !isWeatherEquipmentId(String(e.equipment_id ?? "")));
      setRowCount(eq?.sampling?.row_count ?? 0);
      setEqKind(
        cookbookKind(eq?.equipment_type || selected?.equipment_type || "—"),
      );
    } catch {
      /* mapping / registry optional for first paint */
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
      });
      if (!body.ok) {
        throw new Error(body.error || "Central analytics failed");
      }
      setOverview(body);
      setVavHealthToken((n) => n + 1);
      hasOverview.current = true;
      const results = await getFddResults(buildingId).catch(() => null);
      if (results) setLastRuleResultCount(results.length);
    } catch (err) {
      setOverviewErr(formatErr(err));
      if (!hasOverview.current) {
        setOverview(null);
      }
    } finally {
      setLoadingOverview(false);
    }
  }, [buildingId, equipment]);

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  useEffect(() => {
    if (lastBuildingId.current !== buildingId) {
      lastBuildingId.current = buildingId;
      hasOverview.current = false;
      setOverview(null);
      setOverviewErr(null);
    }
  }, [buildingId]);

  useEffect(() => {
    if (!buildingId) return;
    void refreshMeta();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingId]);

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
      // Same tuning source as Vibe19: package session_config.params (confirm_min=0
      // etc.), then Lab localStorage overrides.
      const prev = await getSessionConfig().catch(() => null);
      const params = effectiveRunParams(
        prev?.config?.params as Record<string, unknown> | undefined,
        loadLocalRuleParams(),
      );
      await putSessionConfig({
        ...(prev?.config ?? {}),
        schema_version: prev?.config?.schema_version ?? SESSION_SCHEMA,
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

  const busy = loadingOverview && !overview;
  const datasetStart = formatOverviewTs(overview?.span?.start ?? firstTs);
  const datasetEnd = formatOverviewTs(overview?.span?.end ?? lastTs);

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

  const tableCount = (() => {
    if (!overview) return 0;
    let n = 0;
    if (overview.motor_weekly.table?.length) n += 1;
    if (overview.mech_cooling.bins?.length) n += 1;
    if (overview.economizer_weather.table?.length) n += 1;
    if (overview.economizer_free_cooling.metrics?.length) n += 1;
    if (overview.bas_vs_web_oat.hist_table?.length) n += 1;
    if (overview.devices_by_type?.length) n += 1;
    return n;
  })();

  return (
    <div
      className={`overview-populated${busy ? " overview-populated--busy" : ""}`}
      data-testid="overview-populated"
      aria-busy={busy || undefined}
    >
      <p className="oracle-sidebar__caption">
        Overview analytics from central DataFusion. Tables and health matrices
        live here; Plotly charts moved to RCx Plots. CSV overlay is under Inspect.
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

      {loadingOverview && overview ? (
        <p className="oracle-sidebar__caption" data-testid="overview-refreshing">
          Refreshing analytics…
        </p>
      ) : null}

      {!busy && overview ? (
        <InlineAlert
          id="overview-charts-ready"
          variant="info"
          testId="overview-charts-ready"
        >
          Tables ready: <strong>{tableCount}</strong> tabulated section
          {tableCount === 1 ? "" : "s"} for <code>{buildingId}</code> (
          {overview.elapsed_s}s · {overview.source}). Motor / economizer / OAT
          figures are on <strong>RCx Plots</strong>.
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
            }}
            testId="overview-refresh"
          />
          <p className="oracle-sidebar__caption">
            Manual — builds building charts when you click
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
            Manual — DataFusion FDD registry → Results / FDD Plots
          </p>
        </div>
        {overview ? (
          <span className="oracle-sidebar__caption">
            {overview.elapsed_s}s · {overview.equipment_count} equip ·{" "}
            {overview.source}
          </span>
        ) : (
          <span className="oracle-sidebar__caption" data-testid="overview-idle-hint">
            Click <strong>Update analytics</strong> to load building charts
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
        Two manual actions: <strong>Update analytics</strong> builds Overview
        tables and health matrices; <strong>Run all rules</strong> runs the FDD SQL
        registry. Sidebar <strong>Update this rule</strong> re-runs one rule.
        Equipment for Inspect / FDD Plots is chosen in those sections — not here.
      </p>

      <SectionTabs activeSectionId="overview" embedded />

      <div className="overview-metrics" data-testid="overview-metrics">
        <Metric
          id="ov-eq"
          label="Equipment"
          value={String(
            overview?.equipment_count && overview.equipment_count > 0
              ? overview.equipment_count
              : equipment.length,
          )}
          testId="overview-eq-count"
        />
        <Metric id="ov-rules" label="Rules" value={String(ruleCount)} testId="overview-rule-count" />
        <Metric id="ov-rows" label="Rows (selected)" value={String(rowCount)} testId="overview-row-count" />
        <Metric id="ov-poll" label="Poll (s)" value="300" testId="overview-poll" />
        <Metric id="ov-kind" label="Kind" value={eqKind} testId="overview-kind" />
      </div>
      <p className="oracle-sidebar__caption" data-testid="overview-rule-caption">
        +4 SQL rollups
      </p>
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

      <PlantHealthSections buildingId={buildingId} refreshToken={vavHealthToken} />
      <VavHealthSection buildingId={buildingId} refreshToken={vavHealthToken} />

      <section className="overview-section" data-testid="overview-motor-runtime">
        <h3>Motor / equipment run hours</h3>
        <p className="oracle-sidebar__caption">
          {overview?.motor_weekly.caption ??
            "Weekly plant motors (AHU fans, boilers, chillers). VAV terminals are excluded. Figures live on RCx Plots."}
        </p>
        {(overview?.motor_weekly.plants ?? []).map((plant) => (
          <div key={plant.plant_group} data-testid={`overview-motor-${plant.plant_group}`}>
            <h4>{plant.title}</h4>
            {plant.empty ? (
              <p className="oracle-sidebar__caption">
                No series for {plant.title.split("—")[0]?.trim().toLowerCase()}.
              </p>
            ) : (
              <p className="oracle-sidebar__caption">
                Plot moved to RCx family preset (
                {plant.plant_group === "air"
                  ? "ahu_motor_weekly"
                  : plant.plant_group === "boiler"
                    ? "boiler_motor_weekly"
                    : "chiller_motor_weekly"}
                ).
              </p>
            )}
          </div>
        ))}
        {!overview && !loadingOverview ? (
          <p className="oracle-sidebar__caption">No motor table yet.</p>
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
            "Chillers / DX / VRF compressor-proof; never CHW valves. Figure on RCx Plots (mech_cooling_oat_bins)."}
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
        {overview && !overview.mech_cooling.bins?.length && !loadingOverview ? (
          <p className="oracle-sidebar__caption" data-testid="overview-mech-empty">
            {overview.mech_cooling.caption}
          </p>
        ) : null}
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
        <p className="oracle-sidebar__caption">
          Economizer Plotly (delta, MAT residual, temps overlay) moved to RCx
          presets <code>economizer_delta</code>, <code>economizer_mat_resid</code>,{" "}
          <code>economizer_temps_overlay</code>.
        </p>
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
            "Overlay of BAS OAT and web dry-bulb. Figure on RCx Weather preset bas_vs_web_oat."}
        </p>
        {overview?.bas_vs_web_oat.hist_table?.length ? (
          <DataTable
            id="bas-web-hist-table"
            label="BAS − web OAT deviation histogram"
            columns={Object.keys(overview.bas_vs_web_oat.hist_table[0] ?? {}).map(
              (k) => ({ key: k, header: k }),
            )}
            rows={
              overview.bas_vs_web_oat.hist_table.slice(0, 80) as Array<
                Record<string, string | number>
              >
            }
            testId="overview-bas-hist-table"
          />
        ) : (
          <InlineAlert id="bas-web-need" variant="info">
            Need both BAS outdoor-air temp and web weather OAT for the histogram
            table. Overlay plot is on RCx Plots.
          </InlineAlert>
        )}
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
    </div>
  );
}
