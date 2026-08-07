import { useEffect, useRef, useState } from "react";
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
  createDump,
  downloadDump,
  type WattlabDump,
  type WattlabDumpProfile,
} from "../api/wattlabApi";
import { listPackageBuildings } from "../api/mappingApi";
import { importFuelCampus } from "../api/fuelApi";

const WATTLab_PAGES = [
  { value: "Uploads", label: "Uploads" },
  { value: "Fuel dashboard", label: "Fuel dashboard" },
  { value: "Twin / calibrate", label: "Twin / calibrate" },
  { value: "ECMs", label: "ECMs" },
] as const;

const DUMP_PROFILES: { value: WattlabDumpProfile; label: string }[] = [
  { value: "summary", label: "summary" },
  { value: "diagnostic", label: "diagnostic" },
  { value: "forensic", label: "forensic" },
];

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Vibe 20 Studio workflows + authenticated WattLab dump download. */
export function WattLabPage() {
  const { query, setQuery } = useSessionQuery();
  const page = query.wattlabPage ?? "Uploads";
  const jobId = query.jobId ?? "";
  const buildingId = query.siteId ?? "";

  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [buildings, setBuildings] = useState<string[]>([]);
  const [uri, setUri] = useState("workspace://exports/demo.zip");
  const [profile, setProfile] = useState<WattlabDumpProfile>("summary");
  const [dump, setDump] = useState<WattlabDump | null>(null);
  const [handoffJson, setHandoffJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [fuelCampusId, setFuelCampusId] = useState<string | null>(null);
  const [fuelUploading, setFuelUploading] = useState(false);
  const fuelFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void listJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
    void listPackageBuildings()
      .then(setBuildings)
      .catch(() => setBuildings([]));
  }, []);

  const ensureJob = async (): Promise<string> => {
    if (jobId) return jobId;
    const job = await createJob({
      jobName: `WattLab · ${buildingId || "site"}`,
      description: "react wattlab dump",
    });
    setQuery({ jobId: job.job_id }, true);
    setJobs((prev) => [job, ...prev]);
    return job.job_id;
  };

  const onBuildDump = async () => {
    if (!buildingId) {
      setError("Select an active site (import package first)");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const jid = await ensureJob();
      const artifact = await createDump(jid, buildingId, profile);
      setDump(artifact);
      setUri(artifact.download_url || `workspace://jobs/${jid}/wattlab/dumps/${artifact.dump_id}`);
      setNotice(`Built dump ${artifact.dump_id} (${artifact.filename})`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  const onDownloadDump = async () => {
    if (!dump || !jobId) return;
    setSaving(true);
    setError(null);
    try {
      await downloadDump(jobId, dump.dump_id, dump.filename);
      setNotice(`Downloaded ${dump.filename}`);
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
        source: "react-wattlab-page",
        wattlab_studio_page: page,
        building_id: buildingId || undefined,
        dump_id: dump?.dump_id,
      });
      setHandoffJson(JSON.stringify(handoff, null, 2));
      setNotice(`Created handoff ${String(handoff.handoff_id ?? "")}`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  const onFuelZipSelected = async (file: File | undefined) => {
    if (!file) return;
    setFuelUploading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await importFuelCampus(file);
      const id = res.campus_id ?? res.campus?.campus_id ?? null;
      setFuelCampusId(id);
      setNotice(
        id
          ? `Imported fuel campus ${id}`
          : "Fuel campus import succeeded",
      );
    } catch (err) {
      setFuelCampusId(null);
      setError(formatErr(err));
    } finally {
      setFuelUploading(false);
      if (fuelFileRef.current) fuelFileRef.current.value = "";
    }
  };

  return (
    <AppShell
      title="WattLab"
      caption="Vibe 20 Studio — Uploads / Fuel / Twin / ECMs + dump ZIP"
      activeSectionId="wattlab"
    >
      <div className="page-stack" data-testid="wattlab-page">
        <RadioGroup
          id="wattlab-page"
          label="WattLab workflow"
          description="Maps st.session_state wattlab_studio_page → URL ?wl="
          value={page}
          options={[...WATTLab_PAGES]}
          onChange={(value) => setQuery({ wattlabPage: value }, true)}
          testId="wattlab-page-radio"
        />
        <p data-testid="wattlab-active-page">
          Active: <strong>{page}</strong>
        </p>

        <Select
          id="wattlab-building"
          label="Building / site"
          value={buildingId}
          options={[
            { value: "", label: "— select site —" },
            ...buildings.map((b) => ({ value: b, label: b })),
          ]}
          onChange={(v) => setQuery({ siteId: v || undefined }, true)}
          testId="wattlab-building"
        />

        <Select
          id="wattlab-job"
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

        {page === "Uploads" ? (
          <section data-testid="wattlab-uploads">
            <h3>Uploads</h3>
            <p>
              Build a Vibe19-compatible WattLab dump (v3) from the imported
              package via authenticated{" "}
              <code>POST /api/jobs/&#123;id&#125;/wattlab/dumps</code>.
            </p>
            <Select
              id="wattlab-profile"
              label="Export profile"
              value={profile}
              options={DUMP_PROFILES}
              onChange={(v) => setProfile(v as WattlabDumpProfile)}
              testId="wattlab-profile"
            />
            <div className="oracle-sidebar__btn-row">
              <Button
                id="wattlab-build-dump"
                label={saving ? "Working…" : "Build WattLab dump (zip)"}
                onClick={() => void onBuildDump()}
                disabled={!buildingId || saving}
                testId="wattlab-build-dump"
              />
              <Button
                id="wattlab-dl-dump"
                label="Download WattLab dump (zip)"
                onClick={() => void onDownloadDump()}
                disabled={!dump || !jobId || saving}
                testId="wattlab-dl-dump"
              />
            </div>
            {dump ? (
              <pre data-testid="wattlab-dump-meta">
                {JSON.stringify(dump, null, 2)}
              </pre>
            ) : null}

            <h4>Fuel campus ZIP</h4>
            <p>
              Import campus.json + monthly bill CSVs via{" "}
              <code>POST /api/fuel/campus/import</code> (multipart .zip).
            </p>
            <input
              ref={fuelFileRef}
              id="wattlab-fuel-zip"
              type="file"
              accept=".zip,application/zip"
              hidden
              data-testid="wattlab-fuel-zip-input"
              onChange={(e) =>
                void onFuelZipSelected(e.target.files?.[0] ?? undefined)
              }
            />
            <Button
              id="wattlab-fuel-upload"
              label={
                fuelUploading ? "Importing fuel…" : "Upload fuel campus ZIP"
              }
              onClick={() => fuelFileRef.current?.click()}
              disabled={fuelUploading || saving}
              testId="wattlab-fuel-upload"
            />
            {fuelCampusId ? (
              <p data-testid="wattlab-fuel-campus-id">
                Imported campus_id: <strong>{fuelCampusId}</strong>
              </p>
            ) : null}
          </section>
        ) : null}

        {page === "Fuel dashboard" ? (
          <section data-testid="wattlab-fuel">
            <h3>Fuel dashboard</h3>
            <FuelDashboard />
          </section>
        ) : null}

        {page === "Twin / calibrate" ? (
          <section data-testid="wattlab-twin">
            <h3>Twin / calibrate</h3>
            <p>
              Stub only — EnergyPlus visualizer, G14 crosscheck, and Unity WebGL
              wiring are Phase B follow-up. The Twin page exists for handoff /
              WebGL experiments; this WattLab tab is not a finished calibrate
              workflow.
            </p>
            <Link to="/twin">Open Twin / Unity WebGL</Link>
          </section>
        ) : null}

        {page === "ECMs" ? (
          <section data-testid="wattlab-ecms">
            <h3>ECMs</h3>
            <p>
              Stub only — spreadsheet vs EnergyPlus energy · cost · ROI is Phase
              C follow-up. Dump + handoff artifacts are prerequisites; no ECM
              calc UI is shipped here yet.
            </p>
          </section>
        ) : null}

        <label htmlFor="wattlab-uri">
          portable_zip_uri
          <input
            id="wattlab-uri"
            data-testid="wattlab-uri"
            value={uri}
            onChange={(e) => setUri(e.target.value)}
            style={{ width: "100%" }}
          />
        </label>

        <Button
          id="wattlab-handoff"
          label={saving ? "Working…" : "Create handoff"}
          onClick={() => void onCreateHandoff()}
          disabled={!jobId || saving}
          testId="wattlab-handoff"
        />

        {error ? (
          <InlineAlert id="wattlab-error" variant="danger">
            {error}
          </InlineAlert>
        ) : null}
        {notice ? (
          <InlineAlert id="wattlab-notice" variant="success" testId="wattlab-notice">
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
