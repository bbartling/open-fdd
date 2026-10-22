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
  getFddReadiness,
  runFdd,
  type FddReadiness,
} from "../api/fddApi";
import {
  getPackageMapping,
  getSessionConfig,
  putSessionConfig,
  type MappingEquipment,
  type SessionConfig,
} from "../api/mappingApi";
import {
  beginScopedRequest,
  createScopeHolder,
  isAbortError,
} from "../session/scopedLoad";
import type { OverviewVibe19Response } from "../api/overviewTypes";
import { fetchCentralOverview } from "../api/centralOverview";
import type { FddEquipmentItem } from "../api/analyticsApi";
import { apiFetch } from "../api/client";
import { VavHealthSection } from "./VavHealthSection";
import { PlantHealthSections } from "./PlantHealthSections";
import { WeatherHealthSection } from "./WeatherHealthSection";
import { SqlAnomalySection } from "./SqlAnomalySection";
import { mergeRuleDescriptionsFromApi } from "../lib/ruleLabels";
import { RULES_UPDATED_EVENT } from "./RuleTuningPanel";
import { naturalCompare } from "../lib/naturalSort";
import { displayScalar, storeScalar } from "../api/roleUnits";
import {
  cookbookKind,
  cookbookRuleCount,
  datasetTimeSpan,
  equipmentTypeCountLabel,
  formatOverviewTs,
  isWeatherEquipment,
  spanHoursBetween,
} from "../lib/overviewMetrics";
import {
  DAY_NAMES as DAYS,
  defaultOccupancyWeek,
  occupiedHoursPerWeek,
  scheduleReferenceFromSession,
  type DaySched,
} from "../api/occupancySchedule";

/** Under-hood per-site Overview paint (Wave O7). No UI chrome. */
type OverviewSiteCache = {
  body: OverviewVibe19Response;
  lastRuleResultCount: number | null;
};
const overviewSiteCache = new Map<string, OverviewSiteCache>();

/** Test-only: reset site cache between Vitest cases. */
export function clearOverviewSiteCacheForTests(): void {
  overviewSiteCache.clear();
}
import {
  effectiveRunParams,
  loadLocalRuleParams,
  SESSION_SCHEMA,
} from "../lib/ruleParams";

export function detectedTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Comfort slider tick. Stored bounds stay °F until the slider moves. */
function comfortDisplay(fahrenheit: number, unitSystem: "imperial" | "metric"): number {
  const shown = displayScalar(fahrenheit, "degF", unitSystem);
  if (unitSystem !== "metric") return shown;
  return Math.round(shown * 10) / 10;
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
  const [week, setWeek] = useState(defaultOccupancyWeek);
  const [tz, setTz] = useState(detectedTimeZone);
  const [schedOpen, setSchedOpen] = useState(true);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleNote, setScheduleNote] = useState<string | null>(null);
  const [rulesBusy, setRulesBusy] = useState(false);
  const [rulesNote, setRulesNote] = useState<string | null>(null);
  const [rulesErr, setRulesErr] = useState<string | null>(null);
  const [lastRuleResultCount, setLastRuleResultCount] = useState<number | null>(
    null,
  );
  const [fddReadiness, setFddReadiness] = useState<FddReadiness | null>(null);
  const [readinessSite, setReadinessSite] = useState(buildingId);
  const [analyticsClean, setAnalyticsClean] = useState(false);
  const [afddOwnsRefresh, setAfddOwnsRefresh] = useState(false);
  const [forceRules, setForceRules] = useState(false);
  const [overviewElapsedSec, setOverviewElapsedSec] = useState(0);
  const overviewLoadStarted = useRef<number | null>(null);
  const hasOverview = useRef(false);
  const lastBuildingId = useRef(buildingId);
  const overviewAbort = useRef<AbortController | null>(null);
  const readinessSiteRef = useRef(buildingId);
  const metaHolder = useRef(createScopeHolder());
  const metaSiteRef = useRef(buildingId);
  const framesRef = useRef<MappingEquipment[]>([]);
  readinessSiteRef.current = buildingId;
  if (readinessSite !== buildingId) {
    setReadinessSite(buildingId);
    setFddReadiness(null);
    setLastRuleResultCount(null);
    setRulesNote(null);
  }

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
  const zoneLowDisplay = comfortDisplay(zoneLow, unitSystem);
  const zoneHighDisplay = comfortDisplay(zoneHigh, unitSystem);
  const comfortStep = unitSystem === "metric" ? 0.3 : 0.5;
  const bareMin = occupiedHoursPerWeek(week);
  const spanH =
    overview?.span?.span_hours != null
      ? Math.round(Number(overview.span.span_hours) * 10) / 10
      : spanHoursBetween(firstTs, lastTs);

  const devicesByType = useMemo(() => {
    const CHROME_TYPES = [
      "AHU",
      "VAV",
      "PLANT",
      "HEAT_PUMP",
      "WEATHER",
      "Zone Other",
      "VRF",
      "GENERAL",
    ];
    const map = new Map<string, number>();
    for (const t of CHROME_TYPES) map.set(t, 0);
    const raw = overview?.devices_by_type?.length
      ? overview.devices_by_type.map((r) => ({
          equipment_type: String(r.type || "unknown"),
          count: Number(r.count) || 0,
        }))
      : (() => {
          const m = new Map<string, number>();
          for (const e of equipment) {
            const t = String(e.equipment_type || "unknown");
            m.set(t, (m.get(t) ?? 0) + 1);
          }
          return [...m.entries()].map(([equipment_type, count]) => ({
            equipment_type,
            count,
          }));
        })();
    for (const row of raw) {
      const label = equipmentTypeCountLabel(row.equipment_type);
      map.set(label, (map.get(label) ?? 0) + row.count);
    }
    return [...map.entries()]
      .map(([equipment_type, count]) => ({ equipment_type, count }))
      .sort((a, b) => a.equipment_type.localeCompare(b.equipment_type));
  }, [equipment, overview?.devices_by_type]);

  const equipmentIdRef = useRef(equipmentId);
  const selectedTypeRef = useRef(selected?.equipment_type);
  equipmentIdRef.current = equipmentId;
  selectedTypeRef.current = selected?.equipment_type;

  const paintFrames = useCallback(
    (frames: MappingEquipment[], eqId: string, fallbackType: string | undefined) => {
      const span = datasetTimeSpan(frames);
      setFirstTs(span.start);
      setLastTs(span.end);
      const eq =
        frames.find((item) => item.equipment_id === eqId && !isWeatherEquipment(item)) ??
        frames.find((item) => !isWeatherEquipment(item));
      setRowCount(eq?.sampling?.row_count ?? 0);
      setEqKind(cookbookKind(eq?.equipment_type || fallbackType || "—"));
    },
    [],
  );

  const refreshMeta = useCallback(async () => {
    const ticket = beginScopedRequest(metaHolder.current);
    const siteChanged = metaSiteRef.current !== buildingId;
    metaSiteRef.current = buildingId;
    if (siteChanged) {
      framesRef.current = [];
      paintFrames([], equipmentIdRef.current, selectedTypeRef.current);
    }
    try {
      const [status, rules] = await Promise.all([
        getFddStatus().catch((err: unknown) => {
          if (isAbortError(err)) throw err;
          return null;
        }),
        listFddRules().catch((err: unknown) => {
          if (isAbortError(err)) throw err;
          return [];
        }),
      ]);
      if (!ticket.isCurrent()) return;
      setRuleCount(cookbookRuleCount(rules, status?.rule_count));
      mergeRuleDescriptionsFromApi(rules);
      if (!buildingId) return;
      let map: Awaited<ReturnType<typeof getPackageMapping>> | null = null;
      try {
        map = await getPackageMapping(buildingId, undefined, { signal: ticket.signal });
      } catch (err) {
        if (isAbortError(err)) throw err;
      }
      if (!ticket.isCurrent()) return;
      const frames = map?.equipment ?? [];
      framesRef.current = frames;
      paintFrames(frames, equipmentIdRef.current, selectedTypeRef.current);
    } catch (err) {
      if (isAbortError(err) || !ticket.isCurrent()) return;
    }
  }, [buildingId, paintFrames]);

  const equipmentRef = useRef(equipment);
  equipmentRef.current = equipment;

  const refreshReadiness = useCallback(async () => {
    const site = buildingId;
    if (!site) {
      setFddReadiness(null);
      setLastRuleResultCount(null);
      return null;
    }
    try {
      const ready = await getFddReadiness(site);
      if (readinessSiteRef.current !== site) return null;
      setFddReadiness(ready);
      setLastRuleResultCount(ready.result_count);
      return ready;
    } catch {
      if (readinessSiteRef.current !== site) return null;
      setFddReadiness(null);
      return null;
    }
  }, [buildingId]);

  const refreshOverview = useCallback(
    async (opts?: { force?: boolean }) => {
      if (!buildingId) return;
      const force = opts?.force === true;
      if (!force) {
        const hit = overviewSiteCache.get(buildingId);
        if (hit) {
          setOverview(hit.body);
          if (hit.lastRuleResultCount != null) {
            setLastRuleResultCount(hit.lastRuleResultCount);
          }
          hasOverview.current = true;
          setOverviewErr(null);
          setLoadingOverview(false);
          setAnalyticsClean(true);
          return;
        }
      }
      overviewAbort.current?.abort();
      const ac = new AbortController();
      overviewAbort.current = ac;
      setLoadingOverview(true);
      setOverviewErr(null);
      try {
        const body = await fetchCentralOverview({
          building_id: buildingId,
          equipment: equipmentRef.current,
          signal: ac.signal,
          refresh: force,
        });
        if (ac.signal.aborted) return;
        if (!body.ok) {
          throw new Error(body.error || "Central analytics failed");
        }
        setOverview(body);
        hasOverview.current = true;
        const ready = await refreshReadiness();
        if (ac.signal.aborted || readinessSiteRef.current !== buildingId) return;
        overviewSiteCache.set(buildingId, {
          body,
          lastRuleResultCount: ready?.result_count ?? null,
        });
        setAnalyticsClean(true);
      } catch (err) {
        if (ac.signal.aborted) return;
        setOverviewErr(formatErr(err));
        if (!hasOverview.current) {
          setOverview(null);
        }
        setAnalyticsClean(false);
      } finally {
        if (!ac.signal.aborted) {
          setLoadingOverview(false);
        }
      }
    },
    [buildingId, refreshReadiness],
  );

  useEffect(() => {
    let cancelled = false;
    if (!buildingId) {
      setWeek(defaultOccupancyWeek());
      setTz(detectedTimeZone());
      return;
    }
    // Drop the previous site's calendar immediately. The saved schedule is the
    // site session config, not a browser-global draft.
    setWeek(defaultOccupancyWeek());
    setTz(detectedTimeZone());
    void getSessionConfig(buildingId)
      .then((res) => {
        if (cancelled) return;
        const ref = scheduleReferenceFromSession(res.config, detectedTimeZone());
        setWeek(ref.week);
        setTz(ref.timezone);
      })
      .catch(() => {
        if (cancelled) return;
        setWeek(defaultOccupancyWeek());
        setTz(detectedTimeZone());
      });
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  useEffect(() => {
    if (!buildingId) return;
    // Results-first + readiness, then analytics (cache hit paints instantly).
    void refreshReadiness();
    void refreshOverview();
    void apiFetch<{ ok?: boolean; config?: { mode?: string } }>(
      "/api/afdd/scheduler/status",
    )
      .then((s) => {
        setAfddOwnsRefresh(String(s.config?.mode ?? "").toLowerCase() === "continuous");
      })
      .catch(() => setAfddOwnsRefresh(false));
  }, [buildingId, refreshOverview, refreshReadiness]);

  useEffect(() => {
    return () => {
      overviewAbort.current?.abort();
    };
  }, []);

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  useEffect(() => {
    paintFrames(framesRef.current, equipmentId, selected?.equipment_type);
  }, [equipmentId, selected?.equipment_type, paintFrames]);

  useEffect(() => {
    if (lastBuildingId.current !== buildingId) {
      lastBuildingId.current = buildingId;
      setAnalyticsClean(false);
      setForceRules(false);
      const hit = buildingId ? overviewSiteCache.get(buildingId) : undefined;
      if (hit) {
        setOverview(hit.body);
        if (hit.lastRuleResultCount != null) {
          setLastRuleResultCount(hit.lastRuleResultCount);
        }
        hasOverview.current = true;
        setOverviewErr(null);
        setLoadingOverview(false);
        setAnalyticsClean(true);
      } else {
        hasOverview.current = false;
        setOverview(null);
        setOverviewErr(null);
      }
    }
  }, [buildingId]);

  useEffect(() => {
    void getSessionConfig(buildingId)
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
      const single = detail?.mode === "single";
      setRulesNote(
        single
          ? `Rule ${detail.rule_id} updated · ${n ?? "—"} result row(s)`
          : `Rules updated · ${n ?? "—"} result row(s)`,
      );
      // Matrices join FDD results — bump refresh so health cells leave stale/unknown.
      setVavHealthToken((t) => t + 1);
      void refreshReadiness();
      // Lab single-rule: keep Run-all grey if meta still clean; still refresh analytics.
      if (buildingId) overviewSiteCache.delete(buildingId);
      setAnalyticsClean(false);
      void refreshOverview({ force: true });
    };
    window.addEventListener(RULES_UPDATED_EVENT, onRules);
    return () => window.removeEventListener(RULES_UPDATED_EVENT, onRules);
  }, [buildingId, refreshOverview, refreshReadiness]);

  const saveSchedule = async () => {
    setScheduleBusy(true);
    setScheduleNote(null);
    try {
      const prev = await getSessionConfig(buildingId).catch(() => null);
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
      await putSessionConfig(config, buildingId);
      setScheduleNote(
        `Schedule saved (tz ${tz}, ${bareMin} occ h/wk). Calendar persisted to session config.`,
      );
      setAnalyticsClean(false);
      void refreshReadiness();
      void refreshOverview({ force: true });
    } catch (err) {
      setScheduleNote(formatErr(err));
    } finally {
      setScheduleBusy(false);
    }
  };

  const onUpdateAllRules = async (opts?: { force?: boolean }) => {
    if (!buildingId) {
      setRulesErr("Select an active site first");
      return;
    }
    const force = Boolean(opts?.force || forceRules);
    setRulesBusy(true);
    setRulesErr(null);
    setRulesNote(
      force
        ? "Force re-running all rules after fresh samples…"
        : "Running all rules with tuned params…",
    );
    try {
      // Same tuning source as Vibe19: package session_config.params (confirm_min=0
      // etc.), then Lab localStorage overrides.
      const prev = await getSessionConfig(buildingId).catch(() => null);
      const params = effectiveRunParams(
        prev?.config?.params as Record<string, unknown> | undefined,
        loadLocalRuleParams(buildingId),
        buildingId,
      );
      await putSessionConfig(
        {
          ...(prev?.config ?? {}),
          schema_version: prev?.config?.schema_version ?? SESSION_SCHEMA,
          params: { ...(prev?.config?.params ?? {}), ...params },
        },
        buildingId,
      );
      const result = await runFdd({
        mode: "registry",
        building_id: buildingId,
        params,
        force_new_data: force || undefined,
      });
      const n = result.result_count ?? result.results?.length ?? 0;
      setLastRuleResultCount(n);
      setForceRules(false);
      const runStatus = result.run_status ?? "complete";
      setRulesNote(
        result.skipped_recompute
          ? result.message ||
              "Results current — use Lab single-rule for tuning, or Force after fresh samples"
          : `Ran all rules · ${n} result row(s) · ${runStatus} · ${String(result.total_ms ?? "—")} ms`,
      );
      await refreshReadiness();
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
  const resultRows =
    fddReadiness?.result_count ?? lastRuleResultCount ?? 0;
  const fddPending = resultRows === 0;
  const runAllGrey =
    (afddOwnsRefresh || (Boolean(fddReadiness?.clean) && !forceRules)) &&
    resultRows > 0;
  const updateAnalyticsGrey = analyticsClean && Boolean(overview) && !busy;
  const readinessLabel = (() => {
    if (rulesBusy) return "Running all rules…";
    if (busy || loadingOverview) return "Updating analytics…";
    const runStatus = fddReadiness?.run_status;
    if (runStatus === "failed") {
      return `Run failed (${resultRows} result rows)`;
    }
    if (runStatus === "partial") {
      return `Partial (${resultRows} result rows)`;
    }
    if (afddOwnsRefresh && resultRows > 0) {
      return `AFDD owns refresh (${resultRows} result rows)`;
    }
    if (fddReadiness?.clean && resultRows > 0) {
      return `Results current (${resultRows} result rows)`;
    }
    if (overview && fddPending) return "Needs Run all rules";
    if (overview && resultRows > 0) {
      return `Ready (${resultRows} result rows)`;
    }
    return "Idle";
  })();
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

  return (
    <div
      className={`overview-populated${busy ? " overview-populated--busy" : ""}`}
      data-testid="overview-populated"
      aria-busy={busy || undefined}
    >
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
              Elapsed: <strong>{overviewElapsedSec}s</strong>
            </p>
          </div>
        </div>
      ) : null}

      {loadingOverview && overview ? (
        <InlineAlert
          id="overview-refreshing"
          variant="info"
          testId="overview-refreshing"
        >
          Refreshing analytics…
        </InlineAlert>
      ) : null}

      <InlineAlert
        id="overview-readiness"
        variant={
          readinessLabel.startsWith("Needs")
            ? "warning"
            : readinessLabel.startsWith("Ready")
              ? "info"
              : "info"
        }
        testId="overview-readiness"
      >
        Overview status: <strong data-testid="overview-readiness-label">{readinessLabel}</strong>
        {overview && fddPending && !rulesBusy
          ? " — run Run all rules for health matrices."
          : null}
      </InlineAlert>

      <div className="overview-toolbar" data-testid="overview-actions">
        <div className="overview-toolbar__action">
          <Button
            id="overview-update-analytics"
            label={
              busy
                ? `Updating analytics… ${overviewElapsedSec}s`
                : updateAnalyticsGrey
                  ? "Analytics current"
                  : "Update analytics"
            }
            loading={busy}
            disabled={updateAnalyticsGrey}
            onClick={() => {
              setAnalyticsClean(false);
              setVavHealthToken((t) => t + 1);
              void refreshMeta();
              void refreshOverview({ force: true });
            }}
            testId="overview-refresh"
          />
          {updateAnalyticsGrey ? (
            <Button
              id="overview-force-analytics"
              label="Force refresh analytics"
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setAnalyticsClean(false);
                setVavHealthToken((t) => t + 1);
                void refreshMeta();
                void refreshOverview({ force: true });
              }}
              testId="overview-force-analytics"
            />
          ) : null}
        </div>
        <div className="overview-toolbar__action">
          <Button
            id="overview-run-all-rules"
            label={
              rulesBusy
                ? "Running all rules…"
                : runAllGrey
                  ? afddOwnsRefresh
                    ? "AFDD owns refresh"
                    : "Results current"
                  : "Run all rules"
            }
            loading={rulesBusy}
            disabled={runAllGrey || rulesBusy}
            onClick={() => void onUpdateAllRules()}
            testId="overview-update-all-rules"
          />
          {runAllGrey && !afddOwnsRefresh ? (
            <Button
              id="overview-force-run-all"
              label="Force re-run all (after fresh samples)"
              variant="secondary"
              disabled={rulesBusy}
              onClick={() => {
                // Soft-OPEN R8f: global AFDD owns cohort; force only when operator
                // knows samples are fresh. Prefer Lab single-rule for tuning.
                setForceRules(true);
                void onUpdateAllRules({ force: true });
              }}
              testId="overview-force-run-all"
            />
          ) : null}
        </div>
        {overview ? (
          <span className="oracle-sidebar__caption">
            {overview.elapsed_s}s · {overview.equipment_count} equip ·{" "}
            {overview.source}
          </span>
        ) : (
          <InlineAlert id="overview-idle" variant="info" testId="overview-idle-hint">
            Click <strong>Update analytics</strong> to load tables.
          </InlineAlert>
        )}
      </div>

      {overviewErr ? (
        <InlineAlert id="overview-err" variant="danger" testId="overview-err">
          Central analytics unavailable: {overviewErr}. Confirm the package for{" "}
          <code>{buildingId}</code> is loaded and central is healthy.
        </InlineAlert>
      ) : null}

      <SectionTabs activeSectionId="overview" embedded />

      <div className="overview-metrics" data-testid="overview-metrics">
        <Metric
          id="ov-eq"
          label="Equipment"
          description={
            (overview?.weather_excluded ?? 0) > 0
              ? "Weather is not counted as equipment"
              : undefined
          }
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
        {fddReadiness || lastRuleResultCount != null ? (
          <Metric
            id="ov-rule-results"
            label="Latest FDD result rows"
            value={String(resultRows)}
            testId="overview-rule-result-count"
          />
        ) : null}
      </section>

      <section className="overview-section" data-testid="overview-schedule">
        <h3>Set Building Schedule and Comfort Requirements</h3>
        <Slider
          id="zone-low"
          label={`Zone low ${tempUnit}`}
          min={comfortDisplay(55, unitSystem)}
          max={comfortDisplay(72, unitSystem)}
          step={comfortStep}
          value={zoneLowDisplay}
          onChange={(value) =>
            setZoneLow(storeScalar(value, "degF", unitSystem))
          }
          testId="overview-zone-low"
        />
        <Slider
          id="zone-high"
          label={`Zone high ${tempUnit}`}
          min={comfortDisplay(70, unitSystem)}
          max={comfortDisplay(85, unitSystem)}
          step={comfortStep}
          value={zoneHighDisplay}
          onChange={(value) =>
            setZoneHigh(storeScalar(value, "degF", unitSystem))
          }
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

      <PlantHealthSections
        buildingId={buildingId}
        refreshToken={vavHealthToken}
        pendingFlags={fddPending}
      />
      <VavHealthSection
        buildingId={buildingId}
        refreshToken={vavHealthToken}
        pendingFlags={fddPending}
      />
      <WeatherHealthSection
        buildingId={buildingId}
        refreshToken={vavHealthToken}
        equipment={equipment}
      />
      <SqlAnomalySection buildingId={buildingId} refreshToken={vavHealthToken} />

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
