import { useEffect, useState } from "react";
import { Link } from "react-router";
import { getHistorianOrphans, type HistorianOrphansResponse } from "../api/historianApi";
import { isAbortError } from "../session/scopedLoad";
import { InlineAlert } from "./widgets";

const MAX_NAMED_EQUIPMENT = 5;

function equipmentSummary(equipment: string[]): string {
  if (equipment.length === 0) return "";
  const named = equipment.slice(0, MAX_NAMED_EQUIPMENT).join(", ");
  const rest = equipment.length - MAX_NAMED_EQUIPMENT;
  return rest > 0 ? `${named} and ${rest} more` : named;
}

/**
 * Data health alert card. Warns when historian series are no longer in the
 * building model (orphaned after a portal inventory sync) and links to Jobs,
 * where an operator can purge them.
 */
export function DataHealthCard({
  buildingId,
  refreshToken = 0,
}: {
  buildingId: string;
  refreshToken?: number;
}) {
  const [orphans, setOrphans] = useState<HistorianOrphansResponse | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setOrphans(null);
    getHistorianOrphans(buildingId, ctrl.signal)
      .then((res) => {
        if (!ctrl.signal.aborted) setOrphans(res);
      })
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted && !isAbortError(err)) setOrphans(null);
      });
    return () => ctrl.abort();
  }, [buildingId, refreshToken]);

  const count = orphans?.ok ? orphans.orphaned_points : 0;
  if (count <= 0 || !orphans) return null;

  const equipment = equipmentSummary(orphans.equipment ?? []);
  const series = count === 1 ? "series is" : "series are";

  return (
    <InlineAlert
      id="overview-data-health"
      variant="warning"
      title="Data health:"
      testId="overview-data-health"
    >
      <span data-testid="overview-data-health-summary">
        {count} historian {series} no longer in the building model
        {equipment ? ` (${equipment})` : ""}. Their samples are kept until purged.
      </span>{" "}
      <Link
        to={`/jobs?site=${encodeURIComponent(buildingId)}`}
        data-testid="overview-data-health-jobs-link"
      >
        Review on Jobs
      </Link>
    </InlineAlert>
  );
}
