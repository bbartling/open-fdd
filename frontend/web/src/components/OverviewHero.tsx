export interface OverviewHeroProps {
  buildingId?: string;
  buildingCount?: number;
  populated?: boolean;
}

const STACK_LABEL =
  "Open-FDD stack: NF and CSV ingest, Rust, Timescale, React, and Haystack RDF";

/**
 * Current product stack. NF and CSV are the ingest path. Rust writes Timescale.
 * React is the product UI. Haystack RDF is the model, not a second historian.
 */
function OverviewStack() {
  return (
    <svg
      className="oracle-hero__logo"
      viewBox="0 0 720 260"
      role="img"
      aria-labelledby="openfdd-stack-title"
      data-testid="oracle-hero-logo"
    >
      <title id="openfdd-stack-title">{STACK_LABEL}</title>
      <rect className="oracle-hero__stack-box" x="16" y="16" width="168" height="72" rx="8" />
      <text className="oracle-hero__stack-label" x="100" y="46" textAnchor="middle">
        NF
      </text>
      <text className="oracle-hero__stack-sub" x="100" y="68" textAnchor="middle">
        ingest
      </text>
      <rect className="oracle-hero__stack-box" x="16" y="108" width="168" height="72" rx="8" />
      <text className="oracle-hero__stack-label" x="100" y="138" textAnchor="middle">
        CSV
      </text>
      <text className="oracle-hero__stack-sub" x="100" y="160" textAnchor="middle">
        ingest
      </text>
      <rect className="oracle-hero__stack-box" x="260" y="62" width="160" height="72" rx="8" />
      <text className="oracle-hero__stack-label" x="340" y="104" textAnchor="middle">
        Rust
      </text>
      <rect className="oracle-hero__stack-box" x="500" y="16" width="200" height="72" rx="8" />
      <text className="oracle-hero__stack-label" x="600" y="58" textAnchor="middle">
        Timescale
      </text>
      <rect className="oracle-hero__stack-box" x="500" y="108" width="200" height="72" rx="8" />
      <text className="oracle-hero__stack-label" x="600" y="150" textAnchor="middle">
        React
      </text>
      <rect className="oracle-hero__stack-box" x="240" y="188" width="200" height="56" rx="8" />
      <text className="oracle-hero__stack-label" x="340" y="222" textAnchor="middle">
        Haystack RDF
      </text>
      <path
        className="oracle-hero__stack-arrow"
        d="M184 52 H230 L260 80 M184 144 H230 L260 116"
        fill="none"
      />
      <path className="oracle-hero__stack-arrow" d="M420 98 H500 M600 88 V108" fill="none" />
      <path className="oracle-hero__stack-arrow" d="M340 134 V188" fill="none" />
    </svg>
  );
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
      {populated && buildingId ? (
        <p className="oracle-hero__tagline" data-testid="oracle-hero-site">
          Active site <code>{buildingId}</code>
          {buildingCount > 1 ? ` · ${buildingCount} buildings loaded` : ""}
        </p>
      ) : null}
      <div className="oracle-hero__logo-wrap">
        <OverviewStack />
      </div>
    </header>
  );
}
