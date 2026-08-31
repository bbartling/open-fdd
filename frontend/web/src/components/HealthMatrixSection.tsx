import { useEffect, useMemo, useState } from "react";
import { DataTable, InlineAlert } from "./widgets";
import type { AnalyticsEnvelope } from "../api/analyticsApi";
import { healthColumnHeader } from "../lib/cookbookRuleCatalog";
import { naturalCompare } from "../lib/naturalSort";

export function tri(v: unknown): string {
  if (v === true) return "true";
  if (v === false) return "false";
  return "unknown";
}

function fmtHours(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(1);
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

export interface HealthMatrixSectionProps {
  family: string;
  title: string;
  caption: string;
  buildingId: string;
  refreshToken: number;
  fetchHealth: (buildingId: string) => Promise<AnalyticsEnvelope>;
  flagColumns: HealthFlagColumn[];
  /** Custom clean/empty state copy. */
  emptyMessage?: string;
  /** Keep the table headers visible when rows are empty. */
  renderEmptyTable?: boolean;
}

export function HealthMatrixSection({
  family,
  title,
  caption,
  buildingId,
  refreshToken,
  fetchHealth,
  flagColumns,
  emptyMessage,
  renderEmptyTable = false,
}: HealthMatrixSectionProps) {
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const test = (suffix: string) => `${family}-health-${suffix}`;
  const sectionId = `overview-${family}-health`;

  useEffect(() => {
    if (!buildingId) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void fetchHealth(buildingId)
      .then((e) => {
        if (!cancelled) setEnv(e);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setEnv(null);
          setErr(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [buildingId, refreshToken, fetchHealth]);

  const rows = useMemo(
    () =>
      [...(env?.rows ?? [])].sort((a, b) =>
        naturalCompare(String(a.equipment_id ?? ""), String(b.equipment_id ?? "")),
      ),
    [env?.rows],
  );

  const empty = !loading && !err && env !== null && rows.length === 0;

  const tableColumns = useMemo(() => {
    const cols: Array<{ key: string; header: string }> = [
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
  }, [flagColumns]);

  const matrixRows = rows.slice(0, 400).map((r) => {
    const out: Record<string, unknown> = {
      score_label: String(r.score_label ?? ""),
      equipment_id: String(r.equipment_id ?? ""),
      total_fault_h: fmtHours(r.total_fault_h),
    };
    for (const col of flagColumns) {
      out[col.key] = tri(r[col.key]);
      const fhKey = col.faultHoursKey ?? `${col.key}_fault_h`;
      out[`${col.key}_fault_h`] = fmtHours(r[fhKey]);
    }
    return out;
  });

  const showTable = matrixRows.length > 0 || (empty && renderEmptyTable);

  return (
    <section
      className={`overview-${family}-health`}
      data-testid={sectionId}
      aria-labelledby={`${sectionId}-heading`}
    >
      <h3 id={`${sectionId}-heading`}>{title}</h3>
      <p className="oracle-sidebar__caption">{caption}</p>
      {loading ? (
        <InlineAlert id={`${family}-health-loading`} variant="info" testId={test("loading")}>
          Loading {title}…
        </InlineAlert>
      ) : null}
      {err ? (
        <InlineAlert id={`${family}-health-err`} variant="danger" testId={test("err")}>
          {err}
        </InlineAlert>
      ) : null}
      {empty ? (
        <InlineAlert id={`${family}-health-empty`} variant="info" testId={test("empty")}>
          {emptyMessage ?? (
            <>
              No {family.toUpperCase()} equipment in this data model. Run{" "}
              <strong>Update analytics</strong> / <strong>Run all rules</strong> after mapping.
            </>
          )}
        </InlineAlert>
      ) : null}
      {showTable ? (
        <DataTable
          id={`${family}-health-table`}
          label={`${title} matrix`}
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
