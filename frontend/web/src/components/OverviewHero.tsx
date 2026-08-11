const DOCS_URL = "https://bbartling.github.io/open-fdd/";
const REPO_URL = "https://github.com/bbartling/open-fdd";

export interface OverviewHeroProps {
  buildingId?: string;
  buildingCount?: number;
  populated?: boolean;
}

/**
 * Persistent Overview hero. Same node whether inventory is empty or loaded —
 * logo must not unmount when equipment arrives (vibe19 layout oracle).
 */
export function OverviewHero({
  buildingId,
  buildingCount = 0,
  populated = false,
}: OverviewHeroProps) {
  return (
    <header className="oracle-hero" data-testid="oracle-hero">
      <h1 className="oracle-hero__title">Open FDD</h1>
      <p className="oracle-hero__tagline">
        Fault detection + WattLab energy twin — sites, FDD, and calibrated
        models.
      </p>
      {populated && buildingId ? (
        <p className="oracle-hero__tagline" data-testid="oracle-hero-site">
          Active site <code>{buildingId}</code>
          {buildingCount > 1 ? ` · ${buildingCount} buildings loaded` : ""}
        </p>
      ) : null}
      <div className="oracle-hero__logo-wrap">
        <img
          className="oracle-hero__logo"
          src="/image_new_chiller.png"
          alt="open-fdd — Rust-native HVAC fault detection at the edge"
          width={720}
          height={405}
          data-testid="oracle-hero-logo"
        />
      </div>
      <div className="oracle-hero__how" data-testid="oracle-hero-how">
        <h2>How it works (2 pieces + run)</h2>
        <ol>
          <li>
            <strong>Data package</strong> — sidebar Building package zip (
            <code>openfdd_package_v1</code>). Sites tab picks the active
            building.
          </li>
          <li>
            <strong>Data model</strong> — column→role map for that site (Data
            Model tab or session_config / Haystack JSON in the zip).
          </li>
          <li>
            <strong>Run</strong> — Overview <strong>Update analytics</strong>{" "}
            (building charts) then <strong>Run all rules</strong> (FDD). Then
            FDD Plots / RCx Plots. WattLab is a later tab, not step 3.
          </li>
        </ol>
        <p>
          <a href={DOCS_URL} target="_blank" rel="noreferrer">
            Open-FDD docs
          </a>
          {" · "}
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            Open-FDD repo
          </a>
        </p>
      </div>
    </header>
  );
}
