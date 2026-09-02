import { useEffect, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import { FuelDashboard } from "../components/FuelDashboard";
import { useSessionQuery } from "../session";
import {
  Button,
  InlineAlert,
  RadioGroup,
  Select,
} from "../components/widgets";
import { listJobs, createJob, type JobMeta } from "../api/jobsApi";
import { createWattlabHandoff } from "../api/reportsApi";
import {
  createExport,
  downloadExport,
  type EngineeringExport,
  type ExportProfile,
} from "../api/exportApi";
import { LockedSiteCaption } from "../components/LockedSiteCaption";

const EXPORT_PAGES = [
  { value: "Uploads", label: "Uploads" },
  { value: "Fuel dashboard", label: "Fuel dashboard" },
  { value: "Twin / calibrate", label: "Twin / calibrate" },
  { value: "ECMs", label: "ECMs" },
] as const;

const EXPORT_PROFILES: { value: ExportProfile; label: string }[] = [
  { value: "summary", label: "summary" },
  { value: "diagnostic", label: "diagnostic" },
  { value: "forensic", label: "forensic" },
];

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Engineering & ML export workflows + authenticated bundle download. */
export function ExportPage() {
  const { query, setQuery } = useSessionQuery();
  const page = query.wattlabPage ?? "Uploads";
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
      jobName: `Export · ${buildingId || "site"}`,
      description: "engineering & ML bundle export",
    });
    setQuery({ jobId: job.job_id }, true);
    setJobs((prev) => [job, ...prev]);
    return job.job_id;
  };

  const onBuildBundle = async () => {
    if (!buildingId) {
      setError("Lock a site on Overview first (import a package if needed)");
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
      setNotice(`Built bundle ${artifact.export_id} (${artifact.filename})`);
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
        source: "react-export-page",
        wattlab_studio_page: page,
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
      title="Export & ML"
      caption="Engineering & ML bundle export — utilities ship with package import"
      activeSectionId="export"
    >
      <div className="page-stack" data-testid="wattlab-page">
        <RadioGroup
          id="export-page"
          label="Export workflow"
          description="Package utilities ingest on Upload; fuel analytics on Fuel dashboard"
          value={page}
          options={[...EXPORT_PAGES]}
          onChange={(value) => setQuery({ wattlabPage: value }, true)}
          testId="wattlab-page-radio"
        />
        <p data-testid="wattlab-active-page">
          Active: <strong>{page}</strong>
        </p>

        <LockedSiteCaption buildingId={buildingId} testId="locked-site" />

        <Select
          id="export-job"
          label="Job"
          value={jobId}
          options={[
            { value: "", label: "— auto-create on export —" },
            ...jobs.map((j) => ({
              value: j.job_id,
              label: `${j.job_name} (${j.job_id})`,
            })),
          ]}
          onChange={(v) => setQuery({ jobId: v || undefined }, true)}
          testId="wattlab-job"
        />

        {page === "Uploads" ? (
          <section data-testid="wattlab-uploads">
            <h3>Engineering &amp; ML bundle</h3>
            <p>
              Build an <code>openfdd_engineering_bundle_v1</code> ZIP from the
              imported package (Rust-first; no Python in central image).
            </p>
            <Select
              id="export-profile"
              label="Export profile"
              value={profile}
              options={EXPORT_PROFILES}
              onChange={(v) => setProfile(v as ExportProfile)}
              testId="wattlab-profile"
            />
            <div className="oracle-sidebar__btn-row">
              <Button
                id="export-build-bundle"
                label={saving ? "Working…" : "Build Engineering & ML Bundle"}
                onClick={() => void onBuildBundle()}
                disabled={!buildingId || saving}
                testId="wattlab-build-dump"
              />
              <Button
                id="export-dl-bundle"
                label="Download bundle (zip)"
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
        ) : null}

        {page === "Fuel dashboard" ? (
          <section data-testid="wattlab-fuel">
            <h3>Fuel dashboard</h3>
            <p>
              Utility bills and submeters load via package import under{" "}
              <code>utilities/</code>.
            </p>
            <FuelDashboard />
          </section>
        ) : null}

        {page === "Twin / calibrate" ? (
          <section data-testid="wattlab-twin">
            <h3>Twin / calibrate</h3>
            <p>
              Stub only — EnergyPlus visualizer, G14 crosscheck, and Unity WebGL
              wiring are Phase B follow-up.
            </p>
            <Link to="/twin">Open Twin / Unity WebGL</Link>
          </section>
        ) : null}

        {page === "ECMs" ? (
          <section data-testid="wattlab-ecms">
            <h3>ECMs</h3>
            <p>
              Stub only — spreadsheet vs EnergyPlus energy · cost · ROI is Phase
              C follow-up. Bundle + handoff artifacts are prerequisites.
            </p>
          </section>
        ) : null}

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
