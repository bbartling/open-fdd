import { useEffect, useMemo, useState } from "react";
import { useExplicitAnalyticsRefresh } from "../session/useExplicitAnalyticsRefresh";
import { DataTable, InlineAlert } from "./widgets";
import type { DataTableColumn } from "./widgets/DataTable";
import type { AnalyticsEnvelope } from "../api/analyticsApi";
import { healthColumnHeader } from "../lib/cookbookRuleCatalog";
import { naturalCompare } from "../lib/naturalSort";

const DIAGNOSTIC_SCHEMA = "diagnostic_matrix_v1";

/** Display flag cell. Pending = FDD not run yet (avoid raw "unknown"). */
export function tri(v: unknown, opts?: { pending?: boolean }): string {
  if (v === true) return "true";
  if (v === false) return "false";
  if (opts?.pending) return "—";
  return "unknown";
}

function fmtHours(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(1);
}

function fmtCount(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return v.trim();
  return "—";
}

function rowText(row: Record<string, unknown>, key: string): string {
  const value = row[key];
  return typeof value === "string" ? value : "";
}

function proxyFlag(row: Record<string, unknown>): string | null {
  for (const key of ["flag", "fault_flag", "hunt_flag"]) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function isAbortError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === "AbortError") ||
    (err instanceof Error && err.name === "AbortError")
  );
}

function envelopeSite(env: AnalyticsEnvelope): string {
  if (env.site_id && env.site_id.trim()) return env.site_id;
  if (env.building_id && env.building_id.trim()) return env.building_id;
  for (const row of env.rows) {
    const site = rowText(row, "site_id") || rowText(row, "building_id");
    if (site) return site;
  }
  return "";
}

export function isDiagnosticMatrix(env: AnalyticsEnvelope | null): boolean {
  if (!env) return false;
  if (env.schema_version === DIAGNOSTIC_SCHEMA) return true;
  return env.rows.some(
    (row) => typeof row.role === "string" && proxyFlag(row) !== null,
  );
}

export function healthMatrixRowKey(
  buildingId: string,
  row: Record<string, unknown>,
): string {
  const explicit = rowText(row, "row_key");
  if (explicit) return explicit;
  const site = rowText(row, "site_id") || rowText(row, "building_id") || buildingId;
  return [site, rowText(row, "equipment_id"), rowText(row, "role")].join("\u001f");
}

function diagnosticFlagHeader(
  env: AnalyticsEnvelope,
  rows: Record<string, unknown>[],
): string {
  if (env.query_id === "pid-hunting") return "hunt";
  if (env.query_id === "sensor-faults") return "fault";
  let fault = false;
  let hunt = false;
  for (const row of rows) {
    const kind = rowText(row, "flag_kind");
    if (kind === "fault" || typeof row.fault_flag === "string") fault = true;
    if (kind === "hunt" || typeof row.hunt_flag === "string") hunt = true;
  }
  if (fault && !hunt) return "fault";
  if (hunt && !fault) return "hunt";
  return "flag";
}

export function healthRowClassFullyBroken(score: unknown): string | undefined {
  const match = String(score ?? "").match(/^(\d+)\/(\d+)$/);
  if (!match) return undefined;
  const hit = Number(match[1]);
  const total = Number(match[2]);
  return total > 0 && hit === total ? "health-row--broken-3" : undefined;
}

/** @internal compatibility export for existing tests/callers. */
export const healthRowClassBroken3Only = healthRowClassFullyBroken;

/** @deprecated retained for legacy 3-dimension table tests. */
export function healthRowClass(score: unknown): string | undefined {
  switch (String(score ?? "")) {
    case "1/3":
      return "health-row--broken-1";
    case "2/3":
      return "health-row--broken-2";
    case "3/3":
      return "health-row--broken-3";
    default:
      return undefined;
  }
}

export interface HealthFlagColumn {
  key: string;
  ruleId: string;
  haystackTags?: string[];
  /** Row field for fault hours (defaults to `{key}_fault_h`). */
  faultHoursKey?: string;
}

export interface HealthFetchOptions {
  refresh?: boolean;
  signal?: AbortSignal;
}

export interface HealthMatrixSectionProps {
  family: string;
  title: string;
  /** @deprecated Quiet UI — captions are not rendered. */
  caption?: string;
  buildingId: string;
  refreshToken: number;
  fetchHealth: (
    buildingId: string,
    opts?: HealthFetchOptions,
  ) => Promise<AnalyticsEnvelope>;
  flagColumns: HealthFlagColumn[];
  /** Custom clean/empty state copy. */
  emptyMessage?: string;
  /** Keep the table headers visible when rows are empty. */
  renderEmptyTable?: boolean;
  /**
   * When true, missing flags show "—" (pending) instead of "unknown".
   * Use until Run all rules has produced FDD result rows.
   */
  pendingFlags?: boolean;
}

export function HealthMatrixSection({
  family,
  title,
  buildingId,
  refreshToken,
  fetchHealth,
  flagColumns,
  emptyMessage,
  renderEmptyTable = false,
  pendingFlags = false,
}: HealthMatrixSectionProps) {
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [scopeId, setScopeId] = useState(buildingId);
  if (scopeId !== buildingId) {
    setScopeId(buildingId);
    setEnv(null);
    setErr(null);
    setLoading(true);
  }

  const test = (suffix: string) => `${family}-health-${suffix}`;
  const sectionId = `overview-${family}-health`;
  const refresh = useExplicitAnalyticsRefresh(buildingId, refreshToken);

  useEffect(() => {
    if (!buildingId) {
      setEnv(null);
      setErr(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setErr(null);
    const opts: HealthFetchOptions = { signal: controller.signal };
    if (refresh) opts.refresh = true;
    void fetchHealth(buildingId, opts)
      .then((envelope) => {
        if (!active || controller.signal.aborted) return;
        const claimed = envelopeSite(envelope);
        if (claimed && claimed !== buildingId) return;
        setEnv(envelope);
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted || isAbortError(error)) return;
        setEnv(null);
        setErr(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (active && !controller.signal.aborted) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [buildingId, refreshToken, fetchHealth, refresh]);

  const rows = useMemo(() => {
    const kept = (env?.rows ?? []).filter((row) => {
      const site = rowText(row, "site_id") || rowText(row, "building_id");
      return !site || site === buildingId;
    });
    kept.sort((a, b) => {
      const byEquip = naturalCompare(
        rowText(a, "equipment_id"),
        rowText(b, "equipment_id"),
      );
      if (byEquip !== 0) return byEquip;
      return naturalCompare(rowText(a, "role"), rowText(b, "role"));
    });
    return kept;
  }, [env?.rows, buildingId]);

  const diagnostic = isDiagnosticMatrix(env);
  const empty = !loading && !err && env !== null && rows.length === 0;

  const tableColumns = useMemo((): DataTableColumn<Record<string, unknown>>[] => {
    if (diagnostic && env) {
      const header = diagnosticFlagHeader(env, rows);
      return [
        { key: "equipment_id", header: "equip" },
        { key: "role", header: "role" },
        { key: "flag", header },
        { key: "n", header: "n" },
      ];
    }
    const cols: DataTableColumn<Record<string, unknown>>[] = [
      { key: "equipment_id", header: "equip" },
    ];
    for (const col of flagColumns) {
      const full = healthColumnHeader(col.ruleId, col.haystackTags);
      cols.push({
        key: col.key,
        header: col.ruleId,
        headerTitle: full,
      });
      cols.push({
        key: `${col.key}_fault_h`,
        header: `${col.ruleId} h`,
        headerTitle: `${col.ruleId} fault_h`,
      });
    }
    cols.push({ key: "total_fault_h", header: "total fault_h" });
    return cols;
  }, [diagnostic, env, rows, flagColumns]);

  const matrixRows = useMemo(() => {
    const seen = new Set<string>();
    const out: Record<string, unknown>[] = [];
    for (const row of rows) {
      const rowKey = healthMatrixRowKey(buildingId, row);
      if (seen.has(rowKey)) {
        if (diagnostic) {
          const incoming = proxyFlag(row);
          const existing = out.find((item) => item.row_key === rowKey);
          if (
            existing &&
            incoming &&
            incoming.toUpperCase() !== "OK" &&
            String(existing.flag).toUpperCase() === "OK"
          ) {
            existing.flag = incoming;
          }
        }
        continue;
      }
      seen.add(rowKey);
      if (diagnostic) {
        out.push({
          row_key: rowKey,
          equipment_id: rowText(row, "equipment_id"),
          role: rowText(row, "role"),
          flag: proxyFlag(row) ?? "unknown",
          n: fmtCount(row.n),
        });
      } else {
        const record: Record<string, unknown> = {
          row_key: rowKey,
          score_label: String(row.score_label ?? ""),
          equipment_id: rowText(row, "equipment_id"),
          total_fault_h: fmtHours(row.total_fault_h),
        };
        for (const col of flagColumns) {
          record[col.key] = tri(row[col.key], { pending: pendingFlags });
          const fhKey = col.faultHoursKey ?? `${col.key}_fault_h`;
          record[`${col.key}_fault_h`] = fmtHours(row[fhKey]);
        }
        out.push(record);
      }
      if (out.length >= 400) break;
    }
    return out;
  }, [rows, buildingId, diagnostic, flagColumns, pendingFlags]);

  const showTable = matrixRows.length > 0 || (empty && renderEmptyTable);

  return (
    <section
      className={`overview-${family}-health`}
      data-testid={sectionId}
      aria-labelledby={`${sectionId}-heading`}
    >
      <h3 id={`${sectionId}-heading`}>{title}</h3>
      {loading ? (
        <InlineAlert id={`${family}-health-loading`} variant="info" testId={test("loading")}>
          Loading…
        </InlineAlert>
      ) : null}
      {err ? (
        <InlineAlert id={`${family}-health-err`} variant="danger" testId={test("err")}>
          {err}
        </InlineAlert>
      ) : null}
      {empty ? (
        <InlineAlert id={`${family}-health-empty`} variant="info" testId={test("empty")}>
          {emptyMessage ?? <>No {family.toUpperCase()} equipment in this data model.</>}
        </InlineAlert>
      ) : null}
      {pendingFlags && !diagnostic && matrixRows.length > 0 ? (
        <InlineAlert
          id={`${family}-health-pending`}
          variant="info"
          testId={test("pending")}
        >
          Run <strong>Run all rules</strong> to fill health flags.
        </InlineAlert>
      ) : null}
      {showTable ? (
        <DataTable
          id={`${family}-health-table`}
          label={title}
          columns={tableColumns}
          rows={matrixRows}
          rowClassName={(row) =>
            healthRowClassFullyBroken((row as { score_label?: unknown }).score_label)
          }
          testId={test("table")}
        />
      ) : null}
    </section>
  );
}
