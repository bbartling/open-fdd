import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { DataTable, InlineAlert, Button } from "../components/widgets";
import {
  formatDurationMs,
  listActions,
  statusIndicator,
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

export function ActionsPage() {
  const [actions, setActions] = useState<ActionEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [selected, setSelected] = useState<ActionEntry | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await listActions(150);
      setActions(list);
      setError(null);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const hasRunning = actions.some((a) => a.status === "running");
    const interval = window.setInterval(
      () => {
        setNow(Date.now());
        void refresh();
      },
      hasRunning ? 1500 : 8000,
    );
    return () => window.clearInterval(interval);
  }, [actions, refresh]);

  const rows = actions.map((a) => ({
    status: `${statusIndicator(a.status)} ${a.status}`,
    started_at: a.started_at,
    finished_at: a.finished_at ?? "—",
    duration: formatDurationMs(elapsedMs(a, now)),
    kind: a.kind,
    label: a.label,
    id: a.id,
  }));

  return (
    <AppShell
      title="Actions"
      caption="Durable backend run log (FDD, imports, analytics)."
      activeSectionId="actions"
    >
      <div className="page-stack" data-testid="actions-page">
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <Button
            id="actions-refresh"
            label={loading ? "Loading…" : "Refresh"}
            onClick={() => void refresh()}
            testId="actions-refresh"
          />
          <p className="oracle-sidebar__caption">
            Polling GET /api/actions · workspace/data/actions/log.jsonl
          </p>
        </div>
        {error ? (
          <InlineAlert id="actions-error" variant="danger">
            {error}
          </InlineAlert>
        ) : null}
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
          ]}
          rows={rows}
          testId="actions-table"
        />
        {actions.length > 0 ? (
          <div data-testid="actions-detail">
            <h3>Detail</h3>
            <select
              data-testid="actions-detail-pick"
              value={selected?.id ?? actions[0]?.id ?? ""}
              onChange={(e) => {
                const hit = actions.find((a) => a.id === e.target.value) ?? null;
                setSelected(hit);
              }}
            >
              {actions.map((a) => (
                <option key={a.id} value={a.id}>
                  {statusIndicator(a.status)} {a.label}
                </option>
              ))}
            </select>
            <pre
              style={{ maxHeight: 240, overflow: "auto", fontSize: "0.85rem" }}
              data-testid="actions-detail-json"
            >
              {JSON.stringify(
                selected ?? actions[0] ?? null,
                null,
                2,
              )}
            </pre>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
