import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  InlineAlert,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listJobs, type JobMeta } from "../api/jobsApi";
import {
  getJobDispositions,
  getJobFindings,
  putJobDispositions,
  putJobFindings,
  upsertDisposition,
  type Disposition,
  type DispositionsDocument,
  type EngFinding,
  type FindingsDocument,
} from "../api/findingsApi";

type FindingRow = {
  finding_id: string;
  correlation_key: string;
  run_id: string;
  disposition: string;
  notes: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const STATUS_OPTS = [
  { value: "open", label: "open" },
  { value: "confirmed", label: "confirmed" },
  { value: "dismissed", label: "dismissed" },
  { value: "deferred", label: "deferred" },
];

export function FindingsPage() {
  const { query, setQuery } = useSessionQuery();
  const jobId = query.jobId ?? "";

  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [findingsDoc, setFindingsDoc] = useState<FindingsDocument>({
    schema_version: "1",
    findings: [],
  });
  const [dispDoc, setDispDoc] = useState<DispositionsDocument>({
    schema_version: "1",
    dispositions: [],
  });
  const [selectedKey, setSelectedKey] = useState("");
  const [status, setStatus] = useState("open");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!jobId) {
      setFindingsDoc({ schema_version: "1", findings: [] });
      setDispDoc({ schema_version: "1", dispositions: [] });
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [f, d] = await Promise.all([
        getJobFindings(jobId),
        getJobDispositions(jobId),
      ]);
      setFindingsDoc(f);
      setDispDoc(d);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void listJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const dispByKey = useMemo(() => {
    const m = new Map<string, Disposition>();
    for (const d of dispDoc.dispositions) {
      m.set(d.correlation_key, d);
    }
    return m;
  }, [dispDoc]);

  const rows: FindingRow[] = useMemo(() => {
    return findingsDoc.findings.map((f: EngFinding) => {
      const d = dispByKey.get(f.correlation_key);
      return {
        finding_id: f.finding_id,
        correlation_key: f.correlation_key,
        run_id: String(f.run_id ?? ""),
        disposition: d?.status ?? "—",
        notes: String(d?.notes ?? ""),
      };
    });
  }, [findingsDoc, dispByKey]);

  const onSelectFinding = (key: string) => {
    setSelectedKey(key);
    const d = dispByKey.get(key);
    setStatus(d?.status ?? "open");
    setNotes(String(d?.notes ?? ""));
  };

  const onSaveDisposition = async () => {
    if (!jobId || !selectedKey) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = upsertDisposition(dispDoc, {
        correlation_key: selectedKey,
        status,
        notes,
        updated_at: new Date().toISOString(),
      });
      await putJobDispositions(jobId, next);
      setDispDoc(next);
      setNotice(`Saved disposition for ${selectedKey}`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  const onSeedDemoFinding = async () => {
    if (!jobId) return;
    setSaving(true);
    setError(null);
    try {
      const seeded: FindingsDocument = {
        schema_version: "1",
        findings: [
          ...findingsDoc.findings,
          {
            finding_id: `finding-${Date.now()}`,
            correlation_key: `rule:DEMO:equip:AHU-1`,
            run_id: "demo-run",
            evidence: { note: "seeded from React FindingsPage" },
          },
        ],
      };
      await putJobFindings(jobId, seeded, `react-${Date.now()}`);
      setFindingsDoc(seeded);
      setNotice("Seeded demo finding (PUT /findings)");
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell
      title="Findings"
      caption="Job engineering findings + dispositions (P1-M5-D)"
      activeSectionId="results"
    >
      <div className="page-stack" data-testid="findings-page">
        <InlineAlert id="findings-scope" variant="info">
          Durable job findings via `/api/jobs/{"{id}"}/findings|dispositions`. FDD
          registry run results remain on{" "}
          <Link to="/rules">Run Rules</Link>.
        </InlineAlert>

        <Select
          id="findings-job"
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
          testId="findings-job"
        />

        {!jobId && (
          <InlineAlert id="findings-need-job" variant="warning">
            Select a job (or open with ?job=).
          </InlineAlert>
        )}

        {error && (
          <InlineAlert id="findings-error" variant="danger">
            {error}
          </InlineAlert>
        )}
        {notice && (
          <InlineAlert id="findings-notice" variant="success" testId="findings-notice">
            {notice}
          </InlineAlert>
        )}

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Button
            id="findings-reload"
            label={loading ? "Loading…" : "Reload"}
            onClick={() => void refresh()}
            disabled={!jobId || loading}
            testId="findings-reload"
          />
          <Button
            id="findings-seed"
            label="Seed demo finding"
            variant="secondary"
            onClick={() => void onSeedDemoFinding()}
            disabled={!jobId || saving}
            testId="findings-seed"
          />
        </div>

        <p data-testid="findings-count">
          {rows.length} finding(s) · findings_revision on job meta when saved
        </p>

        <div data-testid="findings-table-wrap">
          <DataTable
            id="findings-table"
            label="Findings"
            columns={[
              { key: "finding_id", header: "finding_id" },
              { key: "correlation_key", header: "correlation_key" },
              { key: "run_id", header: "run_id" },
              { key: "disposition", header: "disposition" },
              { key: "notes", header: "notes" },
            ]}
            rows={rows}
            loading={loading}
            testId="findings-table"
          />
          <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
            {rows.map((r) => (
              <Button
                key={r.correlation_key}
                id={`findings-pick-${r.finding_id}`}
                label={`Select ${r.correlation_key}`}
                variant="secondary"
                density="compact"
                onClick={() => onSelectFinding(r.correlation_key)}
                testId={`findings-pick-${r.correlation_key}`}
              />
            ))}
          </div>
        </div>

        <section data-testid="findings-disposition-editor">
          <h3>Disposition</h3>
          <Select
            id="findings-selected"
            label="correlation_key"
            value={selectedKey}
            options={[
              { value: "", label: "— select finding —" },
              ...rows.map((r) => ({
                value: r.correlation_key,
                label: r.correlation_key,
              })),
            ]}
            onChange={onSelectFinding}
            testId="findings-selected"
          />
          <Select
            id="findings-status"
            label="status"
            value={status}
            options={STATUS_OPTS}
            onChange={setStatus}
            testId="findings-status"
          />
          <label htmlFor="findings-notes">
            notes
            <textarea
              id="findings-notes"
              data-testid="findings-notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{ width: "100%" }}
            />
          </label>
          <Button
            id="findings-save-disp"
            label={saving ? "Saving…" : "Save disposition"}
            onClick={() => void onSaveDisposition()}
            disabled={!jobId || !selectedKey || saving}
            testId="findings-save-disp"
          />
        </section>
      </div>
    </AppShell>
  );
}
