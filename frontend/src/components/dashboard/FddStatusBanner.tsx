import { useFddStatus } from "@/hooks/use-fdd-status";
import { useSites } from "@/hooks/use-sites";
import { useActiveFaults } from "@/hooks/use-faults";
import { timeAgo } from "@/lib/utils";

export function FddStatusBanner() {
  const { data: fddStatus } = useFddStatus();
  const { data: sites } = useSites();
  const { data: faults } = useActiveFaults();

  const lastRun = fddStatus?.last_run;

  return (
    <div className="border-b border-border/40 bg-muted/30 px-6 py-2.5">
      <div className="mx-auto max-w-7xl text-sm text-muted-foreground">
        {lastRun ? (
          <span>
            Last FDD run{" "}
            <span className="font-medium text-foreground">
              {timeAgo(lastRun.run_ts)}
            </span>
            <span className="mx-1.5 text-border">&middot;</span>
            <span className="font-variant-numeric tabular-nums">
              {sites?.length ?? "\u2026"}
            </span>
            {" "}site{sites?.length !== 1 ? "s" : ""}
            <span className="mx-1.5 text-border">&middot;</span>
            <span className="font-medium text-foreground tabular-nums">
              {faults?.length ?? "\u2026"}
            </span>
            {" "}fault{faults?.length !== 1 ? "s" : ""} found
          </span>
        ) : (
          <span>No FDD runs recorded yet</span>
        )}
      </div>
    </div>
  );
}
