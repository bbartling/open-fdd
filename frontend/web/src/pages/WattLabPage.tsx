import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { useSessionQuery } from "../session";
import { Button, InlineAlert } from "../components/widgets";
import { createJob } from "../api/jobsApi";
import {
  createExport,
  downloadExport,
  type EngineeringExport,
} from "../api/exportApi";
import { LockedSiteCaption } from "../components/LockedSiteCaption";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * One Dump control — EnergyPlus / AI-agent engineering bundle only.
 * No profile radios, no Related Upload/Metering/Twin links, no handoff URI.
 */
export function ExportPage() {
  const { query, setQuery } = useSessionQuery();
  const jobId = query.jobId ?? "";
  const buildingId = query.siteId ?? "";

  const [bundle, setBundle] = useState<EngineeringExport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setBundle(null);
    setNotice(null);
    setError(null);
  }, [buildingId]);

  const ensureJob = async (): Promise<string> => {
    if (jobId) return jobId;
    const job = await createJob({
      jobName: `E+ dump · ${buildingId || "site"}`,
      description: "EnergyPlus / agent engineering bundle",
    });
    setQuery({ jobId: job.job_id }, true);
    return job.job_id;
  };

  const onDump = async () => {
    if (!buildingId) {
      setError("Lock a site on Overview first");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const jid = await ensureJob();
      const artifact = await createExport(jid, buildingId, "summary");
      setBundle(artifact);
      await downloadExport(jid, artifact.export_id, artifact.filename);
      setNotice(`Downloaded ${artifact.filename}`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell
      title="Dump"
      caption="One EnergyPlus / AI-agent engineering dump for the locked site."
      activeSectionId="export"
    >
      <div className="page-stack" data-testid="wattlab-page">
        <LockedSiteCaption buildingId={buildingId} testId="locked-site" />

        <section data-testid="wattlab-uploads">
          <h3>EnergyPlus agent dump</h3>
          <p>
            Builds an <code>openfdd_engineering_bundle_v1</code> ZIP from the
            active site package and downloads it. No other dump modes.
          </p>
          <div className="oracle-sidebar__btn-row">
            <Button
              id="export-build-bundle"
              label={saving ? "Working…" : "Dump"}
              onClick={() => void onDump()}
              disabled={!buildingId || saving}
              testId="wattlab-build-dump"
            />
          </div>
          {bundle ? (
            <pre data-testid="wattlab-dump-meta">
              {JSON.stringify(bundle, null, 2)}
            </pre>
          ) : null}
        </section>

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
      </div>
    </AppShell>
  );
}

export { ExportPage as WattLabPage };
