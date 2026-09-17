import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { useSessionQuery } from "../session";
import { Button, Checkbox, InlineAlert, RadioGroup } from "../components/widgets";
import { createJob } from "../api/jobsApi";
import {
  createExport,
  downloadExport,
  type EngineeringExport,
  type ExportKind,
} from "../api/exportApi";
import { LockedSiteCaption } from "../components/LockedSiteCaption";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Export tab — two dump choices: EnergyPlus/agent engineering bundle or ordinary CSV.
 */
export function ExportPage() {
  const { query, setQuery } = useSessionQuery();
  const jobId = query.jobId ?? "";
  const buildingId = query.siteId ?? "";

  const [kind, setKind] = useState<ExportKind>("energyplus");
  const [includeFaults, setIncludeFaults] = useState(false);
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
      jobName: `Export · ${buildingId || "site"}`,
      description: "Site data export",
    });
    setQuery({ jobId: job.job_id }, true);
    return job.job_id;
  };

  const onBuildDownload = async () => {
    if (!buildingId) {
      setError("Lock a site on Overview first");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const jid = await ensureJob();
      const artifact = await createExport(jid, buildingId, {
        kind,
        includeFaults: kind === "csv" ? includeFaults : undefined,
      });
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
      caption="Download site data for agents or spreadsheets."
      activeSectionId="export"
    >
      <div className="page-stack" data-testid="wattlab-page">
        <LockedSiteCaption buildingId={buildingId} testId="locked-site" />

        <section data-testid="wattlab-uploads">
          <RadioGroup
            id="export-dump-kind"
            label="Dump type"
            testId="export-dump-kind"
            value={kind}
            onChange={(v) => setKind(v as ExportKind)}
            options={[
              {
                value: "energyplus",
                label: "EnergyPlus / agent dump",
                description: "For EnergyPlus / AI agents — engineering bundle ZIP.",
              },
              {
                value: "csv",
                label: "Ordinary CSV",
                description: "For Excel / sheets; optional fault column.",
              },
            ]}
          />

          {kind === "csv" ? (
            <Checkbox
              id="export-include-faults"
              label="Include faults as a column"
              testId="export-include-faults"
              checked={includeFaults}
              onChange={setIncludeFaults}
            />
          ) : null}

          <div className="oracle-sidebar__btn-row">
            <Button
              id="export-build-bundle"
              label={saving ? "Working…" : "Build & download"}
              onClick={() => void onBuildDownload()}
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
