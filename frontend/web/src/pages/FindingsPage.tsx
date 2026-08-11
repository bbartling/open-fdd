import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  Expander,
  InlineAlert,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { LockedSiteCaption } from "../components/LockedSiteCaption";
import {
  getFddResults,
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
  const i = ruleId.indexOf("-");
  return i > 0 ? ruleId.slice(0, i) : ruleId || "other";
}

/** Streamlit Results by Category — FDD results grouped by rule family. */
export function FindingsPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const jobId = query.jobId ?? "";

  const [results, setResults] = useState<FddResultRow[]>([]);
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

  const refreshResults = useCallback(async () => {
    if (!buildingId) {
      setResults([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setResults(await getFddResults(buildingId));
    } catch (err) {
      setError(formatErr(err));
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [buildingId]);

  useEffect(() => {
    void listJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    void refreshResults();
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

  const tableRows = filtered.map((r) => ({
    category: familyOf(String(r.rule_id ?? "")),
    rule_id: String(r.rule_id ?? ""),
    equipment_id: String(r.equipment_id ?? ""),
    status: String(r.status ?? "—"),
    fault_hours: r.fault_hours != null ? String(r.fault_hours) : "—",
    fault_pct: r.fault_pct != null ? String(r.fault_pct) : "—",
  }));

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
    <AppShell
      title="Results by Category"
      caption="FDD rule results grouped by family — run FDD from Overview or the left rail first"
      activeSectionId="results"
    >
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
            No site locked — pick a building on Overview, then run FDD or{" "}
            <strong>Update this rule</strong> in the left rail.
          </InlineAlert>
        ) : null}
        <DataTable
          id="results-by-category"
          label="Results by category"
          columns={[
            { key: "category", header: "category" },
            { key: "rule_id", header: "rule_id" },
            { key: "equipment_id", header: "equipment_id" },
            { key: "status", header: "status" },
            { key: "fault_hours", header: "fault_hours" },
            { key: "fault_pct", header: "fault_pct" },
          ]}
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
          <Button
            id="hitl-open"
            label="Mark selected open (demo)"
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
    </AppShell>
  );
}
