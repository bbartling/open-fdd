import { useState } from "react";
import { useSessionQuery } from "../session";
import { AppShell } from "../components/AppShell";
import { FuelDashboard } from "../components/FuelDashboard";
import { MvChangePointPanel } from "../components/MvChangePointPanel";
import { InlineAlert, RadioGroup } from "../components/widgets";
import { Link } from "react-router";

/**
 * Metering binds to package utilities (utilities_v1 / wrapper utility_bills_monthly.csv)
 * imported with the building package on Uploads / Sites — not a separate fuel campus ZIP.
 * M&V radio hosts the thin IPMVP Option C twin charts (Wave S4 Soft-OPEN).
 */
export function MeteringPage() {
  const { query } = useSessionQuery();
  const siteId = query.siteId ?? "";
  const [section, setSection] = useState<"utilities" | "mv">("utilities");

  return (
    <AppShell
      title="Metering"
      caption="Package utilities + thin M&V twin — Portfolio / Monthly / Weather / Demand / DQ / M&V"
      activeSectionId="metering"
    >
      <div className="page-stack" data-testid="metering-page">
        <RadioGroup
          id="metering-section"
          label="Metering section"
          testId="metering-section"
          value={section}
          onChange={(v) => setSection(v as "utilities" | "mv")}
          options={[
            {
              value: "utilities",
              label: "Utilities",
              description:
                "Package utilities monthly / weather / demand (Fuel dashboard).",
            },
            {
              value: "mv",
              label: "M&V",
              description:
                "IPMVP Option C monthly 2P OLS twin (demo seed → /api/analytics/mv).",
            },
          ]}
        />

        {section === "utilities" ? (
          <>
            <InlineAlert id="metering-scope" variant="info" testId="metering-scope">
              Import a building package with <code>utilities_v1</code> (or wrapper{" "}
              <code>utility_bills_monthly.csv</code>, e.g. Creekside) on{" "}
              <Link to="/upload">Upload</Link> / <Link to="/sites">Sites</Link>.
              Metering reads package utilities for the active site
              {siteId ? (
                <>
                  {" "}
                  (<code data-testid="metering-active-site">{siteId}</code>)
                </>
              ) : (
                " — lock a site first"
              )}
              . Legacy fuel campus ZIP is not the primary ingest path.
            </InlineAlert>

            <FuelDashboard preferredCampusId={siteId || undefined} />
          </>
        ) : (
          <MvChangePointPanel />
        )}
      </div>
    </AppShell>
  );
}
