import { SiteSelector } from "./SiteSelector";
import { useFddStatus } from "@/hooks/use-fdd-status";
import { timeAgo } from "@/lib/utils";

export function TopBar() {
  const { data: fddStatus } = useFddStatus();
  const lastRun = fddStatus?.last_run;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border/60 bg-card/80 px-6 backdrop-blur-lg">
      <SiteSelector />
      <div className="text-sm text-muted-foreground">
        {lastRun ? (
          <span>
            Last FDD run{" "}
            <span className="font-medium text-foreground">
              {timeAgo(lastRun.run_ts)}
            </span>
          </span>
        ) : (
          <span>No FDD runs yet</span>
        )}
      </div>
    </header>
  );
}
