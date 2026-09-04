import { useEffect, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import { useSessionQuery } from "../session";
import { Button, InlineAlert, Select } from "../components/widgets";
import { listJobs, createJob, type JobMeta } from "../api/jobsApi";
import { createWattlabHandoff } from "../api/reportsApi";
import {
  createExport,
  downloadExport,
  type EngineeringExport,
  type ExportProfile,
} from "../api/exportApi";
import { LockedSiteCaption } from "../components/LockedSiteCaption";

const EXPORT_PROFILES: { value: ExportProfile; label: string }[] = [
  { value: "summary", label: "summary" },
  { value: "diagnostic", label: "diagnostic" },
  { value: "forensic", label: "forensic" },
];

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** One Dump page — engineering bundle export only (no Uploads/Fuel/Twin/ECM tabs). */
export function ExportPage() {
  const { query, setQuery } = useSessionQuery();
  const jobId = query.jobId ?? "";
  const buildingId = query.siteId ?? "";

  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [uri, setUri] = useState("workspace://exports/demo.zip");
  const [profile, setProfile] = useState<ExportProfile>("summary");
  const [bundle, setBundle] = useState<EngineeringExport | null>(null);
  const [handoffJson, setHandoffJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void listJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  const ensureJob = async (): Promise<string> => {
    if (jobId) return jobId;
    const job = await createJob({
      jobName: `Dump · ${buildingId || "site"}`,
      description: "engineering bundle dump",
    });
    setQuery({ jobId: job.job_id }, true);
    setJobs((prev) => [job, ...prev]);
    return job.job_id;
  };

  const onBuildBundle = async () => {
    if (!buildingId) {
      setError("Lock a site on Overview first (import a package via Upload if needed)");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const jid = await ensureJob();
      const artifact = await createExport(jid, buildingId, profile);
      setBundle(artifact);
      setUri(
        artifact.download_url ||
          `workspace://jobs/${jid}/exports/${artifact.export_id}`,
      );
      setNotice(`Built dump ${artifact.export_id} (${artifact.filename})`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  const onDownloadBundle = async () => {
    if (!bundle || !jobId) return;
    setSaving(true);
    setError(null);
    try {
      await downloadExport(jobId, bundle.export_id, bundle.filename);
      setNotice(`Downloaded ${bundle.filename}`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  const onCreateHandoff = async () => {
    if (!jobId) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const handoff = await createWattlabHandoff(jobId, {
        portable_zip_uri: uri,
        source: "react-dump-page",
        wattlab_studio_page: "Dump",
        building_id: buildingId || undefined,
        dump_id: bundle?.export_id,
      });
      setHandoffJson(JSON.stringify(handoff, null, 2));
      setNotice(`Created handoff ${String(handoff.handoff_id ?? "")}`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell
      title="Dump"
      caption="One engineering dump — package ingest is Upload; fuel analytics are Metering"
      activeSectionId="export"
    >
      <div className="page-stack" data-testid="wattlab-page">
        <LockedSiteCaption buildingId={buildingId} testId="locked-site" />

        <p data-testid="dump-related-links" className="oracle-sidebar__caption">
          Related: <Link to="/upload">Upload</Link> (package ingest) ·{" "}
          <Link to="/metering">Metering</Link> (utilities / fuel) ·{" "}
          <Link to="/twin">Twin</Link>
        </p>

        <Select
          id="export-job"
          label="Job"
          value={jobId}
          options={[
            { value: "", label: "— auto-create on dump —" },
            ...jobs.map((j) => ({
              value: j.job_id,
              label: `${j.job_name} (${j.job_id})`,
            })),
          ]}
          onChange={(v) => setQuery({ jobId: v || undefined }, true)}
          testId="wattlab-job"
        />

        <section data-testid="wattlab-uploads">
          <h3>Engineering dump</h3>
          <p>
            Build an <code>openfdd_engineering_bundle_v1</code> ZIP from the
            active site package (Rust-first).
          </p>
          <Select
            id="export-profile"
            label="Dump profile"
            value={profile}
            options={EXPORT_PROFILES}
            onChange={(v) => setProfile(v as ExportProfile)}
            testId="wattlab-profile"
          />
          <div className="oracle-sidebar__btn-row">
            <Button
              id="export-build-bundle"
              label={saving ? "Working…" : "Build dump"}
              onClick={() => void onBuildBundle()}
              disabled={!buildingId || saving}
              testId="wattlab-build-dump"
            />
            <Button
              id="export-dl-bundle"
              label="Download dump (zip)"
              onClick={() => void onDownloadBundle()}
              disabled={!bundle || !jobId || saving}
              testId="wattlab-dl-dump"
            />
          </div>
          {bundle ? (
            <pre data-testid="wattlab-dump-meta">
              {JSON.stringify(bundle, null, 2)}
            </pre>
          ) : null}
        </section>

        <label htmlFor="export-uri">
          portable_zip_uri
          <input
            id="export-uri"
            data-testid="wattlab-uri"
            value={uri}
            onChange={(e) => setUri(e.target.value)}
            style={{ width: "100%" }}
          />
        </label>

        <Button
          id="export-handoff"
          label={saving ? "Working…" : "Create handoff"}
          onClick={() => void onCreateHandoff()}
          disabled={!jobId || saving}
          testId="wattlab-handoff"
        />

        {error ? (
          <InlineAlert id="export-error" variant="danger">
            {error}
          </InlineAlert>
        ) : null}
        {notice ? (
          <InlineAlert id="export-notice" variant="success" testId="wattlab-notice">
            {notice}
          </InlineAlert>
        ) : null}
        {handoffJson ? (
          <pre data-testid="wattlab-handoff-json">{handoffJson}</pre>
        ) : null}
      </div>
    </AppShell>
  );
}

/** @deprecated Use ExportPage — kept for bookmarked imports during rename. */
export const WattLabPage = ExportPage;
