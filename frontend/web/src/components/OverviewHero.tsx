const DOCS_URL = "https://bbartling.github.io/open-fdd/";
const REPO_URL = "https://github.com/bbartling/open-fdd";

/** Vibe19-style Overview hero — title, tagline, logo, how-it-works. */
export function OverviewHero() {
  return (
    <header className="oracle-hero" data-testid="oracle-hero">
      <h1 className="oracle-hero__title">Open FDD</h1>
      <p className="oracle-hero__tagline">
        Fault detection + WattLab energy twin — sites, FDD, and calibrated
        models.
      </p>
      <div className="oracle-hero__logo-wrap">
        <img
          className="oracle-hero__logo"
          src="/image_new_chiller.png"
          alt="open-fdd — Rust-native HVAC fault detection at the edge"
          width={720}
          height={405}
        />
      </div>
      <div className="oracle-hero__how">
        <h2>How it works</h2>
        <ol>
          <li>
            <strong>Sites</strong> — Load a package zip; pick the active
            building from the Site list
          </li>
          <li>
            <strong>Data model</strong> — Column→role map for the active site
          </li>
          <li>
            <strong>FDD / WattLab</strong> — Run FDD from Overview or the left
            rail, then WattLab (Fuel / Twin / ECMs) scoped to the site
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
