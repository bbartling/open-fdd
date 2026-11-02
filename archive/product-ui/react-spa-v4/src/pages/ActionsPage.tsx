import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AppShell } from "../components/AppShell";
import { DataTable, InlineAlert, Button } from "../components/widgets";
import {
  clearActions,
  deleteAction,
  formatDurationMs,
  listActions,
  actionDisplayStatus,
  statusIndicator,
  statusLabel,
  type ActionEntry,
} from "../api/actionsApi";
import { ApiClientError } from "../api/client";
import "./ActionsPage.css";

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
  if (status === "partial") return "actions-status actions-status--partial";
  if (status === "fail") return "actions-status actions-status--fail";
  return "actions-status";
}

function StatusBadge({ action }: { action: ActionEntry }) {
  const status = actionDisplayStatus(action);
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
  const skip = asNumber(d.rules_skipped);
  if (ok == null && fail == null && skip == null) return "—";
  return `${ok ?? 0} evaluated / ${fail ?? 0} runtime errors / ${skip ?? 0} ineligible`;
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
  const shown = actionDisplayStatus(action);
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
    metricRows.push({ label: "Runtime errors", value: String(rulesFail) });
  if (rulesSkip != null)
    metricRows.push({ label: "Ineligible skips", value: String(rulesSkip) });
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
          className={statusClass(shown)}
          data-testid="actions-detail-status"
        >
          {statusIndicator(shown)} {statusLabel(shown)}
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
  const [deleteSupported, setDeleteSupported] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await listActions(10);
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
    status: (<StatusBadge action={a} />) as ReactNode,
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
        <p className="muted" data-testid="actions-provider-note">
          Provider poll, backfill, and model activation are not separate action kinds on this API
          yet. Receipts stay empty until those jobs are published. This log remains FDD, import,
          and analytics history.
        </p>
        <div className="actions-toolbar">
          <Button
            id="actions-refresh"
            label={loading ? "Loading…" : "Refresh"}
            onClick={() => void refresh()}
            testId="actions-refresh"
          />
          {deleteSupported && selected ? (
            <Button
              id="actions-delete"
              label={busy ? "Deleting…" : "Delete selected"}
              onClick={() => {
                if (!selected) return;
                setBusy(true);
                void deleteAction(selected.id)
                  .then(() => refresh())
                  .catch((err) => {
                    if (err instanceof ApiClientError && (err.status === 404 || err.status === 405)) {
                      setDeleteSupported(false);
                    }
                    setError(formatErr(err));
                  })
                  .finally(() => setBusy(false));
              }}
              testId="actions-delete"
            />
          ) : null}
          {deleteSupported ? (
            <Button
              id="actions-clear"
              label="Clear all"
              onClick={() => {
                if (!window.confirm("Clear the entire actions log?")) return;
                setBusy(true);
                void clearActions()
                  .then(() => refresh())
                  .catch((err) => {
                    if (err instanceof ApiClientError && (err.status === 404 || err.status === 405)) {
                      setDeleteSupported(false);
                    }
                    setError(formatErr(err));
                  })
                  .finally(() => setBusy(false));
              }}
              testId="actions-clear"
            />
          ) : null}
          <p className="oracle-sidebar__caption">
            Last 10 · Auto-refresh {hasRunning ? "every 1.5s while running" : "every 8s"}
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
            rowClassName={(row) =>
              row.id === selected?.id ? "actions-row--selected" : undefined
            }
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
              className="actions-detail-pick"
              value={selected.id}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {actions.map((a) => {
                const shown = actionDisplayStatus(a);
                return (
                  <option key={a.id} value={a.id}>
                    {statusIndicator(shown)} {statusLabel(shown)} · {a.label}
                  </option>
                );
              })}
            </select>
            <ActionDetailPanel action={selected} now={now} />
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
