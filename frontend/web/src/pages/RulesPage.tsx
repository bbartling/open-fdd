import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  Checkbox,
  DataTable,
  InlineAlert,
  Progress,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  getFddStatus,
  listFddRules,
  runFdd,
  type FddResultRow,
  type FddRuleSummary,
  type FddRunResponse,
  type FddStatus,
} from "../api/fddApi";

type RuleRow = {
  rule_id: string;
  description: string;
  kinds: string;
  selected: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function RulesPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [status, setStatus] = useState<FddStatus | null>(null);
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [runAll, setRunAll] = useState(true);

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<FddRunResponse | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [st, ruleList, blds] = await Promise.all([
        getFddStatus(),
        listFddRules(),
        listPackageBuildings().catch(() => [] as string[]),
      ]);
      setStatus(st);
      setRules(ruleList);
      setBuildings(blds);
      setSelected((prev) => {
        const next = { ...prev };
        for (const r of ruleList) {
          if (next[r.rule_id] === undefined) next[r.rule_id] = false;
        }
        return next;
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

  const selectedIds = useMemo(
    () => Object.entries(selected).filter(([, v]) => v).map(([id]) => id),
    [selected],
  );

  const onRun = async () => {
    if (!buildingId) {
      setError("Select a building (?site=) — FDD runs are building-scoped");
      return;
    }
    if (!runAll && selectedIds.length === 0) {
      setError("Select at least one rule, or enable Run all");
      return;
    }
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setRunning(true);
    setError(null);
    setRunResult(null);
    try {
      const result = await runFdd(
        {
          mode: "registry",
          building_id: buildingId,
          equipment_id: equipmentId || undefined,
          rule_ids: runAll ? undefined : selectedIds,
        },
        { signal: ac.signal },
      );
      setRunResult(result);
    } catch (err) {
      if (ac.signal.aborted) {
        setError("Run cancelled");
      } else {
        setError(formatErr(err));
      }
    } finally {
      setRunning(false);
    }
  };

  const onCancel = () => {
    abortRef.current?.abort();
  };

  const ruleRows: RuleRow[] = rules.map((r) => ({
    rule_id: r.rule_id,
    description: String(r.description ?? ""),
    kinds: (r.equipment_kinds ?? []).join(", "),
    selected: selected[r.rule_id] ? "yes" : "no",
  }));

  const outcomeRows = (runResult?.timings ?? []).map((t) => ({
    rule_id: String(t.rule_id ?? ""),
    status: String(t.status ?? ""),
    ms: String(t.ms ?? ""),
    error: String(t.error ?? ""),
  }));

  const resultPreview: FddResultRow[] = runResult?.results ?? [];

  const buildingOptions = [
    { value: "", label: "— select building —" },
    ...buildings.map((b) => ({ value: b, label: b })),
  ];

  return (
    <AppShell
      title="Run Rules"
      caption="SQL FDD via central Rust / DataFusion (no Python runner)."
      activeSectionId="run-rules"
    >
      <div className="page-placeholder" data-testid="rules-page">
        <h2>FDD run</h2>
        <p>
          <code>POST /api/fdd/run</code> mode=registry. Raw SQL is rejected.
          Building from <code>?site=</code>; optional equipment{" "}
          <code>?eq=</code>. Results also land on{" "}
          <Link to={buildingId ? `/findings?site=${encodeURIComponent(buildingId)}` : "/findings"}>
            Findings
          </Link>
          .
        </p>

        {status ? (
          <p data-testid="fdd-status">
            Registry: {status.rule_count} rules ·{" "}
            <code>{status.rules_dir}</code>
            {status.hint ? ` — ${status.hint}` : ""}
          </p>
        ) : null}

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
          <Select
            id="fdd-building"
            label="Building"
            value={buildingId}
            options={buildingOptions}
            onChange={(value) => setQuery({ siteId: value }, true)}
            testId="fdd-building-select"
          />
          <Checkbox
            id="fdd-run-all"
            label="Run all rules"
            checked={runAll}
            onChange={setRunAll}
            testId="fdd-run-all"
          />
        </div>

        {loading ? <p data-testid="rules-loading">Loading rules…</p> : null}
        {error ? (
          <InlineAlert id="rules-error" variant="danger" testId="rules-error">
            {error}
          </InlineAlert>
        ) : null}

        {running ? (
          <div data-testid="fdd-run-progress">
            <Progress id="fdd-run" label="Running FDD (blocking until DataFusion returns)…" value={0} />
            <Button
              id="fdd-cancel"
              label="Cancel"
              variant="danger"
              onClick={onCancel}
              testId="fdd-cancel"
            />
          </div>
        ) : null}

        <div style={{ display: "flex", gap: "0.5rem", margin: "0.75rem 0" }}>
          <Button
            id="fdd-run"
            label={running ? "Running…" : "Run FDD"}
            onClick={() => void onRun()}
            disabled={running || !buildingId}
            testId="fdd-run"
          />
          <Button
            id="fdd-reload"
            label="Reload catalog"
            variant="secondary"
            onClick={() => void refresh()}
            disabled={running}
            testId="fdd-reload"
          />
        </div>

        {!runAll ? (
          <div data-testid="fdd-rule-pickers" style={{ marginBottom: "1rem" }}>
            <h3>Select rules</h3>
            {rules.map((r) => (
              <Checkbox
                key={r.rule_id}
                id={`rule-${r.rule_id}`}
                label={`${r.rule_id} — ${r.description ?? ""}`}
                checked={Boolean(selected[r.rule_id])}
                onChange={(v) =>
                  setSelected((prev) => ({ ...prev, [r.rule_id]: v }))
                }
                testId={`fdd-rule-${r.rule_id}`}
              />
            ))}
          </div>
        ) : null}

        <DataTable
          id="fdd-rules"
          label="Rule catalog"
          columns={[
            { key: "rule_id", header: "Rule" },
            { key: "description", header: "Description" },
            { key: "kinds", header: "Equipment" },
            { key: "selected", header: "Selected" },
          ]}
          rows={ruleRows}
          testId="fdd-rules-table"
        />

        {runResult ? (
          <div data-testid="fdd-run-summary" style={{ marginTop: "1.25rem" }}>
            <h3>Last run</h3>
            <p>
              succeeded {runResult.rules_succeeded ?? 0} · failed{" "}
              {runResult.rules_failed ?? 0} · skipped{" "}
              {runResult.rules_skipped ?? 0} · {runResult.total_ms ?? 0} ms ·{" "}
              {runResult.engine}
            </p>
            {outcomeRows.length ? (
              <DataTable
                id="fdd-outcomes"
                label="Per-rule outcomes"
                columns={[
                  { key: "rule_id", header: "Rule" },
                  { key: "status", header: "Status" },
                  { key: "ms", header: "ms" },
                  { key: "error", header: "Error" },
                ]}
                rows={outcomeRows}
                testId="fdd-outcomes-table"
              />
            ) : null}
            {resultPreview.length ? (
              <p data-testid="fdd-result-count">
                {resultPreview.length} result row(s) — open{" "}
                <Link
                  to={`/findings?site=${encodeURIComponent(buildingId)}${
                    equipmentId ? `&eq=${encodeURIComponent(equipmentId)}` : ""
                  }`}
                >
                  Findings
                </Link>{" "}
                to filter / download.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
