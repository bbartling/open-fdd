import { useSessionQuery } from "../session";
import { AppShell } from "../components/AppShell";
import { FuelDashboard } from "../components/FuelDashboard";
import { InlineAlert } from "../components/widgets";
import { Link } from "react-router";

/**
 * Metering binds to package utilities (utilities_v1 / wrapper utility_bills_monthly.csv)
 * imported with the building package on Uploads / Sites — not a separate fuel campus ZIP.
 */
export function MeteringPage() {
  const { query } = useSessionQuery();
  const siteId = query.siteId ?? "";

  return (
    <AppShell
      title="Metering"
      caption="Package utilities (monthly + interval) for the active site — Portfolio / Monthly / Weather / Demand / DQ"
      activeSectionId="metering"
    >
      <div className="page-stack" data-testid="metering-page">
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
      </div>
    </AppShell>
  );
}
