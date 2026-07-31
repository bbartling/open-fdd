import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { useSessionQuery } from "../session";
import {
  Button,
  InlineAlert,
  RadioGroup,
  Select,
} from "../components/widgets";
import { listJobs, type JobMeta } from "../api/jobsApi";
import { createWattlabHandoff } from "../api/reportsApi";

const WATTLab_PAGES = [
  { value: "Uploads", label: "Uploads" },
  { value: "Fuel dashboard", label: "Fuel dashboard" },
  { value: "Twin / calibrate", label: "Twin / calibrate" },
  { value: "ECMs", label: "ECMs" },
] as const;

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function WattLabPage() {
  const { query, setQuery } = useSessionQuery();
  const page = query.wattlabPage ?? "Uploads";
  const jobId = query.jobId ?? "";

  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [uri, setUri] = useState("workspace://exports/demo.zip");
  const [handoffJson, setHandoffJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void listJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

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
      title="WattLab"
      caption="Job handoffs via POST /api/jobs/{id}/wattlab/handoffs (P1-M5-E)"
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
          id="wattlab-job"
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
          testId="wattlab-job"
        />

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
          label={saving ? "Creating…" : "Create handoff"}
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
