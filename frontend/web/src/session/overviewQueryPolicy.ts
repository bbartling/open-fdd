import { useSyncExternalStore } from "react";

/**
 * One Overview refresh policy.
 *
 * Opening a site does not send `refresh: true`. An explicit Update / Force
 * marks every Overview query once. A single-rule completion marks only the
 * queries whose flag scope includes that rule. Historian charts are not
 * rule-scoped: a rule run does not recompute them.
 */

export const OVERVIEW_HISTORIAN_QUERY_IDS = [
  "runtime",
  "mechanical-cooling",
  "economizer",
  "bas-vs-web-oat",
] as const;

/** Query id → rule ids that query reads. Match is exact, never a prefix. */
const RULE_SCOPES: ReadonlyArray<readonly [string, readonly string[]]> = [
  ["ahu-temperature-health", ["AHU-SATDEV", "FC2", "FC3", "FC7", "FC13-SAT-HIGH"]],
  ["ahu-pressure-health", ["AHU-DUCTHI", "FC1", "CMD-1", "TRIM-1"]],
  [
    "ahu-economizer-health",
    ["ECON-1", "ECON-2", "ECON-3", "ECON-4", "ECON-5", "ECON-6", "ECON-7"],
  ],
  ["chiller-health", ["CHW-1", "CHW-2", "CHW-3", "CHW-4", "CHW-NOLOAD-1", "TRIM-4"]],
  ["cooling-tower-health", ["CW-APR-1", "CW-FAN-1", "CW-OPT-1"]],
  ["hp-health", ["HP-1", "AHU-SATDEV", "ECON-1"]],
  ["pid-hunting", ["FC4", "PID-HUNT-1"]],
  ["sensor-faults", ["SV-FLATLINE", "SV-RANGE", "SV-RATE", "SV-SPIKE", "SV-STALE"]],
  [
    "zone-other-health",
    ["VAV-1", "SV-FLATLINE", "SV-RANGE", "SV-RATE", "SV-SPIKE", "SV-STALE", "SCHED-1"],
  ],
  ["vav-health", ["VAV-3", "ZONE-COMFORT", "VAV-7"]],
  ["weather-health", ["OAT-METEO", "WX-1", "SENSOR-HI", "SENSOR-LO", "FLATLINE"]],
];

const RULE_QUERY_IDS = RULE_SCOPES.map(([queryId]) => queryId);
const EXPLICIT_EPOCH_QUERIES = [...RULE_QUERY_IDS, "sql-anomaly"];

type Slot = { epoch: number; refreshEpoch: number | null };

const slots = new Map<string, Slot>();
const listeners = new Set<() => void>();
const historianRefresh = new Set<string>();

function slotKey(buildingId: string, queryId: string): string {
  return `${buildingId}\u001f${queryId}`;
}

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function bump(buildingId: string, queryId: string, refresh: boolean): void {
  const id = slotKey(buildingId, queryId);
  const prev = slots.get(id);
  const epoch = (prev?.epoch ?? 0) + 1;
  slots.set(id, { epoch, refreshEpoch: refresh ? epoch : null });
}

/** Queries whose rows depend on this rule. Exact id only. */
export function overviewQueryIdsForRule(ruleId: string): string[] {
  const id = ruleId.trim();
  if (!id) return [];
  const hits: string[] = [];
  for (const [queryId, rules] of RULE_SCOPES) {
    if (rules.includes(id)) hits.push(queryId);
  }
  return hits;
}

export function overviewQueryRequestsRefresh(buildingId: string, queryId: string): boolean {
  const slot = slots.get(slotKey(buildingId, queryId));
  return slot != null && slot.epoch > 0 && slot.refreshEpoch === slot.epoch;
}

export function useOverviewQueryEpoch(buildingId: string, queryId: string): number {
  return useSyncExternalStore(
    subscribe,
    () => slots.get(slotKey(buildingId, queryId))?.epoch ?? 0,
    () => 0,
  );
}

/**
 * Whether the next historian Overview fetch for this site should recompute.
 *
 * The flag stays set until that fetch finishes. React Strict Mode aborts the
 * first effect, and an aborted fetch must still be allowed to recompute.
 */
export function peekOverviewHistorianRefresh(buildingId: string): boolean {
  return historianRefresh.has(buildingId.trim());
}

/** Drop the historian recompute flag after a fetch that was not aborted. */
export function releaseOverviewHistorianRefresh(buildingId: string): void {
  historianRefresh.delete(buildingId.trim());
}

/** Operator Update analytics / Force refresh. One pass over Overview queries. */
export function requestExplicitOverviewRefresh(buildingId: string): void {
  const id = buildingId.trim();
  if (!id) return;
  historianRefresh.add(id);
  for (const queryId of EXPLICIT_EPOCH_QUERIES) bump(id, queryId, true);
  emit();
}

export function noteOverviewRuleCompletion(
  buildingId: string,
  detail: { mode?: string; rule_id?: string; building_id?: string },
): void {
  const id = buildingId.trim();
  if (!id) return;
  if (detail.building_id && detail.building_id !== id) return;
  if (detail.mode === "single") {
    for (const queryId of overviewQueryIdsForRule(detail.rule_id ?? "")) {
      bump(id, queryId, true);
    }
    emit();
    return;
  }
  if (detail.mode === "all" || detail.mode === "registry") {
    for (const queryId of RULE_QUERY_IDS) bump(id, queryId, true);
    emit();
  }
}

export function resetOverviewQueryPolicyForTests(): void {
  slots.clear();
  historianRefresh.clear();
  emit();
}
