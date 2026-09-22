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
    </header>
  );
}
