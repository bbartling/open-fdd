import { useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import { FuelDashboard } from "../components/FuelDashboard";
import { Button, InlineAlert } from "../components/widgets";
import { importFuelCampus } from "../api/fuelApi";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function MeteringPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [campusId, setCampusId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const onFuelZipSelected = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await importFuelCampus(file);
      const id = res.campus_id ?? res.campus?.campus_id ?? null;
      setCampusId(id);
      setReloadToken((n) => n + 1);
    } catch (err) {
      setCampusId(null);
      setError(formatErr(err));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <AppShell
      title="Metering"
      caption="Campus fuel metering via DataFusion — import ZIP, then explore Portfolio / Monthly / Weather / Demand / DQ"
      activeSectionId="metering"
    >
      <div className="page-stack" data-testid="metering-page">
        <InlineAlert id="metering-scope" variant="info">
          Import a fuel campus ZIP (<code>campus.json</code> + bill CSVs) via{" "}
          <code>POST /api/fuel/campus/import</code>, then use the shared Fuel
          dashboard charts.
        </InlineAlert>

        <div className="form-row" style={{ gap: "0.5rem", display: "flex" }}>
          <input
            ref={fileRef}
            id="metering-fuel-zip"
            type="file"
            accept=".zip,application/zip"
            hidden
            data-testid="metering-fuel-zip-input"
            onChange={(e) =>
              void onFuelZipSelected(e.target.files?.[0] ?? undefined)
            }
          />
          <Button
            id="metering-fuel-upload"
            label={uploading ? "Importing fuel…" : "Import fuel campus ZIP"}
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            testId="metering-fuel-upload"
          />
        </div>

        {campusId ? (
          <p data-testid="metering-fuel-campus-id">
            Imported campus_id: <strong>{campusId}</strong>
          </p>
        ) : null}

        {error ? (
          <InlineAlert id="metering-error" variant="danger" testId="metering-error">
            {error}
          </InlineAlert>
        ) : null}

        <FuelDashboard reloadToken={reloadToken} />
      </div>
    </AppShell>
  );
}
