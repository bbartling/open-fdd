import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  DataTable,
  Expander,
  InlineAlert,
  Select,
} from "./widgets";
import { useSessionQuery } from "../session";
import { LockedSiteCaption } from "./LockedSiteCaption";
import {
  getFddResultsDocument,
  type FddResultRow,
} from "../api/fddApi";
import { listJobs, type JobMeta } from "../api/jobsApi";
import {
  getJobDispositions,
  getJobFindings,
  putJobDispositions,
  upsertDisposition,
  type Disposition,
  type DispositionsDocument,
  type EngFinding,
  type FindingsDocument,
} from "../api/findingsApi";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function familyOf(ruleId: string): string {
  if (/^FC\d+/i.test(ruleId)) return "FC";
  const i = ruleId.indexOf("-");
  return i > 0 ? ruleId.slice(0, i) : ruleId || "other";
}

function metricCell(row: FddResultRow): string {
  const metric = row.metric;
  if (!metric || metric.value == null || !Number.isFinite(metric.value)) return "—";
  const unit = metric.unit ? ` ${metric.unit}` : "";
  return `${metric.value}${unit}`;
}

type ResultTableRow = Record<string, unknown> & {
  category: string;
  rule_id: string;
  equipment_id: string;
  status: string;
  fault_hours: string;
  fault_pct: string;
  metric: string;
  metric_window: string;
  metric_provenance: string;
};

/** Effective evaluated window + coverage. Unknown when the historian did not supply bounds. */
export function metricWindow(row: FddResultRow): string {
  const window = row.metric?.window;
  if (!window) return "unknown";
  const unknown =
    window.unknown === true || window.start == null || window.end == null;
  if (unknown) {
    const samples = row.metric?.coverage?.sample_rows;
    const coverage = samples == null ? "" : ` · ${samples} samples`;
    return `unknown${coverage}`;
  }
  const start = window.start;
  const end = window.end;
  const samples = row.metric?.coverage?.sample_rows;
  const coverage = samples == null ? "" : ` · ${samples} samples`;
  return `${start} → ${end}${coverage}`;
}

export function metricProvenance(row: FddResultRow): string {
  const provenance = row.metric?.provenance;
  if (!provenance?.source) return "—";
  const watermark = provenance.watermark ?? row.metric?.window?.watermark;
  const fingerprint = provenance.config_fingerprint;
  const parts = [provenance.source];
  if (watermark) parts.push(`watermark ${watermark}`);
  if (fingerprint) parts.push(`config ${fingerprint.slice(0, 12)}`);
  return parts.join(" · ");
}

/** FDD results grouped by rule family — embedded under Data Model. */
export function ResultsByCategoryPanel() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const jobId = query.jobId ?? "";

  const [results, setResults] = useState<FddResultRow[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [category, setCategory] = useState("(all)");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [findingsDoc, setFindingsDoc] = useState<FindingsDocument>({
    schema_version: "1",
    findings: [],
  });
  const [dispDoc, setDispDoc] = useState<DispositionsDocument>({
    schema_version: "1",
    dispositions: [],
  });
  const [hitlOpen, setHitlOpen] = useState(false);

  const requestGen = useRef(0);

  const refreshResults = useCallback(async () => {
    const site = buildingId;
    const gen = requestGen.current + 1;
    requestGen.current = gen;
    if (!site) {
      setResults([]);
      setRunId(null);
      setRunStatus(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const doc = await getFddResultsDocument(site);
      if (requestGen.current !== gen) return;
      setResults(doc.results);
      setRunId(doc.run_id ?? null);
      setRunStatus(doc.run_status ?? null);
    } catch (err) {
      if (requestGen.current !== gen) return;
      setError(formatErr(err));
      setResults([]);
      setRunId(null);
      setRunStatus(null);
    } finally {
      if (requestGen.current === gen) setLoading(false);
    }
  }, [buildingId]);

  useEffect(() => {
    void listJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    void refreshResults();
    return () => {
      requestGen.current += 1;
    };
  }, [refreshResults]);

  useEffect(() => {
    if (!jobId) {
      setFindingsDoc({ schema_version: "1", findings: [] });
      setDispDoc({ schema_version: "1", dispositions: [] });
      return;
    }
    let cancelled = false;
    void Promise.all([getJobFindings(jobId), getJobDispositions(jobId)])
      .then(([f, d]) => {
        if (!cancelled) {
          setFindingsDoc(f);
          setDispDoc(d);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(formatErr(err));
          setFindingsDoc({ schema_version: "1", findings: [] });
          setDispDoc({ schema_version: "1", dispositions: [] });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const categories = useMemo(() => {
    const s = new Set(results.map((r) => familyOf(String(r.rule_id ?? ""))));
    return ["(all)", ...[...s].sort()];
  }, [results]);

  const filtered = useMemo(() => {
    if (category === "(all)") return results;
    return results.filter(
      (r) => familyOf(String(r.rule_id ?? "")) === category,
    );
  }, [results, category]);

  const tableRows = useMemo((): ResultTableRow[] =>
    filtered.map((r) => ({
      category: familyOf(String(r.rule_id ?? "")),
      rule_id: String(r.rule_id ?? ""),
      equipment_id: String(r.equipment_id ?? ""),
      status: String(r.status ?? "—"),
      fault_hours:
        r.output_kind === "metric" || r.fault_hours == null
          ? "—"
          : String(r.fault_hours),
      fault_pct: r.fault_pct != null ? String(r.fault_pct) : "—",
      metric: metricCell(r),
      metric_window: metricWindow(r),
      metric_provenance: metricProvenance(r),
    })),
  [filtered]);

  const resultColumns = useMemo(
    (): Array<{ key: keyof ResultTableRow & string; header: string }> => [
      { key: "category", header: "category" },
      { key: "rule_id", header: "rule_id" },
      { key: "equipment_id", header: "equipment_id" },
      { key: "status", header: "status" },
      { key: "metric", header: "metric" },
      { key: "metric_window", header: "window" },
      { key: "metric_provenance", header: "provenance" },
      { key: "fault_hours", header: "fault_hours" },
      { key: "fault_pct", header: "fault_pct" },
    ],
    [],
  );

  const dispByKey = useMemo(() => {
    const m = new Map<string, Disposition>();
    for (const d of dispDoc.dispositions) m.set(d.correlation_key, d);
    return m;
  }, [dispDoc]);

  const hitlRows = findingsDoc.findings.map((f: EngFinding) => ({
    finding_id: f.finding_id,
    correlation_key: f.correlation_key,
    disposition: dispByKey.get(f.correlation_key)?.status ?? "—",
    notes: String(dispByKey.get(f.correlation_key)?.notes ?? ""),
  }));

  return (
    <div className="page-stack" data-testid="findings-page">
      <LockedSiteCaption buildingId={buildingId} testId="locked-site" />
      <Select
        id="results-category"
        label="Category"
        value={category}
        options={categories.map((c) => ({ value: c, label: c }))}
        onChange={setCategory}
        testId="results-category"
      />
      <Button
        id="results-refresh"
        label={loading ? "Loading…" : "Refresh results"}
        onClick={() => void refreshResults()}
        disabled={!buildingId || loading}
        testId="results-refresh"
      />
      {error ? (
        <InlineAlert id="results-error" variant="danger">
          {error}
        </InlineAlert>
      ) : null}
      {!buildingId ? (
        <InlineAlert id="results-hint" variant="info">
          No site locked — pick a building on Overview, then run FDD from Lab.
        </InlineAlert>
      ) : null}
      {runId ? (
        <p className="oracle-sidebar__caption" data-testid="results-run-caption">
          Run {runId}
          {runStatus ? ` · ${runStatus}` : ""} · {results.length} rows
        </p>
      ) : null}
      <DataTable
        id="results-by-category"
        label="Results by category"
        columns={resultColumns}
        rows={tableRows}
        loading={loading}
        testId="results-table"
      />

      <Expander
        id="hitl-findings"
        label="Engineering findings HITL (job dispositions)"
        expanded={hitlOpen}
        onChange={setHitlOpen}
        testId="hitl-expander"
      >
        {jobs.length === 0 ? (
          <InlineAlert id="hitl-no-jobs" variant="info" testId="hitl-no-jobs">
            HITL dispositions are available after an engineering findings job has
            produced findings. Bulk FDD results remain available in Results by
            category above.
          </InlineAlert>
        ) : null}
        <Select
          id="hitl-job"
          label="Job"
          value={jobId}
          options={[
            { value: "", label: "— select job —" },
            ...jobs.map((j) => ({
              value: j.job_id,
              label: `${j.job_name} (${j.job_id})`,
            })),
          ]}
          onChange={(v) => setQuery({ jobId: v || undefined }, true)}
          testId="hitl-job"
        />
        <DataTable
          id="hitl-table"
          label="Findings"
          columns={[
            { key: "finding_id", header: "finding_id" },
            { key: "correlation_key", header: "correlation_key" },
            { key: "disposition", header: "disposition" },
            { key: "notes", header: "notes" },
          ]}
          rows={hitlRows}
          testId="hitl-table"
        />
        {jobId && hitlRows.length === 0 ? (
          <InlineAlert
            id="hitl-no-findings"
            variant="info"
            testId="hitl-no-findings"
          >
            This job has no engineering findings to disposition.
          </InlineAlert>
        ) : null}
        <Button
          id="hitl-open"
          label="Mark first finding open"
          disabled={!jobId || !hitlRows[0]}
          onClick={() => {
            if (!jobId || !hitlRows[0]) return;
            const next = upsertDisposition(dispDoc, {
              correlation_key: hitlRows[0].correlation_key,
              status: "open",
              notes: "react results tab",
            });
            void putJobDispositions(jobId, next)
              .then(() => setDispDoc(next))
              .catch((err: unknown) => setError(formatErr(err)));
          }}
          testId="hitl-save"
        />
      </Expander>
    </div>
  );
}
