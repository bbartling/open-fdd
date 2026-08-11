/** Read-only active building. Overview + sidebar are the only editors. */
export function LockedSiteCaption({
  buildingId,
  testId = "locked-site",
}: {
  buildingId: string;
  testId?: string;
}) {
  return (
    <p className="oracle-sidebar__caption" data-testid={testId}>
      {buildingId ? (
        <>
          Active site <code>zip:{buildingId}</code> — change it on Overview or
          sidebar Active site.
        </>
      ) : (
        <>No site locked — pick a building on Overview or sidebar Active site.</>
      )}
    </p>
  );
}
