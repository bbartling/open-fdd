/** Quiet active-site badge — no froofy grey prose when unlocked (use InlineAlert). */
export function LockedSiteCaption({
  buildingId,
  testId = "locked-site",
}: {
  buildingId: string;
  testId?: string;
}) {
  if (!buildingId) return null;
  return (
    <p className="oracle-sidebar__ok" data-testid={testId}>
      <code>zip:{buildingId}</code>
    </p>
  );
}
