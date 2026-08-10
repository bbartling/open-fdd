import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AppShell } from "../components/AppShell";
import { DataTable, InlineAlert, Button } from "../components/widgets";
import {
  formatDurationMs,
  listActions,
  statusIndicator,
  statusLabel,
  type ActionEntry,
} from "../api/actionsApi";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function elapsedMs(a: ActionEntry, now: number): number | null {
  if (a.duration_ms != null) return a.duration_ms;
  if (a.status === "running" && a.started_at) {
    const t = Date.parse(a.started_at);
    if (Number.isFinite(t)) return Math.max(0, now - t);
  }
  return null;
}

function detailRecord(
  detail: ActionEntry["detail"],
): Record<string, unknown> {
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return detail as Record<string, unknown>;
  }
  return {};
}

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) {
    return Number(v);
  }
  return null;
}

function asString(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

function statusClass(status: string): string {
  if (status === "running") return "actions-status actions-status--running";
  if (status === "ok") return "actions-status actions-status--ok";
  if (status === "fail") return "actions-status actions-status--fail";
  return "actions-status";
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={statusClass(status)} data-testid="actions-status-badge">
      {statusIndicator(status)} {statusLabel(status)}
    </span>
  );
}

function rulesSummary(detail: ActionEntry["detail"]): string {
  const d = detailRecord(detail);
  const ok = asNumber(d.rules_succeeded);
  const fail = asNumber(d.rules_failed);
  if (ok == null && fail == null) return "—";
  return `${ok ?? 0}✓ / ${fail ?? 0}✗`;
}

function ActionDetailPanel({
  action,
  now,
}: {
  action: ActionEntry;
  now: number;
}) {
  const detail = detailRecord(action.detail);
  const buildingId =
    asString(detail.building_id) ?? asString(detail.dataset_id);
  const rulesOk = asNumber(detail.rules_succeeded);
  const rulesFail = asNumber(detail.rules_failed);
  const rulesSkip = asNumber(detail.rules_skipped);
  const totalMs = asNumber(detail.total_ms) ?? action.duration_ms ?? null;
  const err = asString(detail.error);
  const elapsed = elapsedMs(action, now);
  const [showRaw, setShowRaw] = useState(false);

  const metricRows: Array<{ label: string; value: string }> = [];
  if (buildingId) metricRows.push({ label: "Building", value: buildingId });
  if (rulesOk != null)
    metricRows.push({ label: "Rules succeeded", value: String(rulesOk) });
  if (rulesFail != null)
    metricRows.push({ label: "Rules failed", value: String(rulesFail) });
  if (rulesSkip != null)
    metricRows.push({ label: "Rules skipped", value: String(rulesSkip) });
  if (asNumber(detail.equipment_written) != null) {
    metricRows.push({
      label: "Equipment written",
      value: String(asNumber(detail.equipment_written)),
    });
  }
  if (asNumber(detail.total_rows) != null) {
    metricRows.push({
      label: "Rows",
      value: String(asNumber(detail.total_rows)),
    });
  }
  if (totalMs != null) {
    metricRows.push({ label: "Server time", value: formatDurationMs(totalMs) });
  }

  return (
    <div className="actions-detail-panel" data-testid="actions-detail-panel">
      <div className="actions-detail-panel__header">
        <span
          className={statusClass(action.status)}
          data-testid="actions-detail-status"
        >
          {statusIndicator(action.status)} {statusLabel(action.status)}
        </span>
        <strong data-testid="actions-detail-label">{action.label}</strong>
      </div>
      <p className="oracle-sidebar__caption" data-testid="actions-detail-kind">
        {action.kind}
        {action.status === "running"
          ? ` · in progress · ${formatDurationMs(elapsed)}`
          : ` · ${formatDurationMs(elapsed)}`}
      </p>
      {action.status === "running" ? (
        <div
          className="actions-detail-panel__pulse"
          data-testid="actions-detail-running"
          role="status"
        >
          Backend work is still running. This panel refreshes automatically.
        </div>
      ) : null}
      {err ? (
        <InlineAlert id="actions-detail-error" variant="danger">
          {err}
        </InlineAlert>
      ) : null}
      {metricRows.length ? (
        <dl className="actions-detail-panel__metrics" data-testid="actions-detail-metrics">
          {metricRows.map((row) => (
            <div key={row.label} className="actions-detail-panel__metric">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <button
        type="button"
        className="oracle-sidebar__btn"
        data-testid="actions-detail-toggle-raw"
        onClick={() => setShowRaw((v) => !v)}
      >
        {showRaw ? "Hide technical detail" : "Show technical detail"}
      </button>
      {showRaw ? (
        <pre
          style={{ maxHeight: 240, overflow: "auto", fontSize: "0.85rem" }}
          data-testid="actions-detail-json"
        >
          {JSON.stringify(action, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

export function ActionsPage() {
  const [actions, setActions] = useState<ActionEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await listActions(150);
      setActions(list);
      setError(null);
      setSelectedId((prev) => {
        if (prev && list.some((a) => a.id === prev)) return prev;
        const running = list.find((a) => a.status === "running");
        if (running) return running.id;
        return list[0]?.id ?? null;
      });
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasRunning = useMemo(
    () => actions.some((a) => a.status === "running"),
    [actions],
  );

  useEffect(() => {
    const interval = window.setInterval(
      () => {
        setNow(Date.now());
        void refresh();
      },
      hasRunning ? 1500 : 8000,
    );
    return () => window.clearInterval(interval);
  }, [hasRunning, refresh]);

  const selected =
    (selectedId && actions.find((a) => a.id === selectedId)) ||
    actions[0] ||
    null;

  const rows: Array<Record<string, unknown>> = actions.map((a) => ({
    status: (<StatusBadge status={a.status} />) as ReactNode,
    started_at: a.started_at,
    finished_at: a.finished_at ?? "—",
    duration: formatDurationMs(elapsedMs(a, now)),
    kind: a.kind,
    label: a.label,
    rules: rulesSummary(a.detail),
    id: a.id,
  }));

  return (
    <AppShell
      title="Actions"
      caption="Durable backend run log (FDD, imports, analytics)."
      activeSectionId="actions"
    >
      <div className="page-stack" data-testid="actions-page">
        <style>{`
          .actions-status { display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 600; }
          .actions-status--running { color: #b45309; animation: actions-pulse 1.4s ease-in-out infinite; }
          .actions-status--ok { color: #15803d; }
          .actions-status--fail { color: #b91c1c; }
          @keyframes actions-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
          .actions-detail-panel {
            border: 1px solid var(--border, #d8d2cc);
            border-radius: 8px;
            padding: 1rem 1.1rem;
            background: var(--surface-2, #faf8f6);
          }
          .actions-detail-panel__header {
            display: flex; flex-wrap: wrap; gap: 0.65rem; align-items: center;
            margin-bottom: 0.35rem;
          }
          .actions-detail-panel__pulse {
            margin: 0.6rem 0;
            padding: 0.55rem 0.75rem;
            border-radius: 6px;
            background: #fff7ed;
            border: 1px solid #fdba74;
            color: #9a3412;
          }
          .actions-detail-panel__metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 0.55rem 1rem;
            margin: 0.85rem 0;
          }
          .actions-detail-panel__metric { margin: 0; }
          .actions-detail-panel__metric dt {
            font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
            color: var(--muted, #6b6560); margin: 0;
          }
          .actions-detail-panel__metric dd {
            margin: 0.15rem 0 0; font-weight: 600; font-variant-numeric: tabular-nums;
          }
          .actions-table-wrap [data-row-id="${selected?.id ?? ""}"] {
            outline: 2px solid color-mix(in srgb, var(--color-primary, #c23b3b) 45%, transparent);
          }
        `}</style>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <Button
            id="actions-refresh"
            label={loading ? "Loading…" : "Refresh"}
            onClick={() => void refresh()}
            testId="actions-refresh"
          />
          <p className="oracle-sidebar__caption">
            Auto-refresh {hasRunning ? "every 1.5s while running" : "every 8s"}
            {" · "}
            GET /api/actions
          </p>
        </div>
        {error ? (
          <InlineAlert id="actions-error" variant="danger">
            {error}
          </InlineAlert>
        ) : null}
        <div className="actions-table-wrap">
          <DataTable
            id="actions-table"
            label="Recent actions"
            columns={[
              { key: "status", header: "Status" },
              { key: "started_at", header: "Started" },
              { key: "finished_at", header: "Finished" },
              { key: "duration", header: "Duration" },
              { key: "kind", header: "Kind" },
              { key: "label", header: "Label" },
              { key: "rules", header: "Rules" },
            ]}
            rows={rows}
            testId="actions-table"
          />
        </div>
        {selected ? (
          <div data-testid="actions-detail">
            <h3>Detail</h3>
            <select
              data-testid="actions-detail-pick"
              value={selected.id}
              onChange={(e) => setSelectedId(e.target.value)}
              style={{ marginBottom: "0.75rem" }}
            >
              {actions.map((a) => (
                <option key={a.id} value={a.id}>
                  {statusIndicator(a.status)} {statusLabel(a.status)} · {a.label}
                </option>
              ))}
            </select>
            <ActionDetailPanel action={selected} now={now} />
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
