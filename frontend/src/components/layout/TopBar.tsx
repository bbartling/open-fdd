import { Sun, Moon, Cloud } from "lucide-react";
import { SiteSelector } from "./SiteSelector";
import { useFddStatus } from "@/hooks/use-fdd-status";
import { useConfig } from "@/hooks/use-config";
import { useTheme } from "@/contexts/theme-context";
import { TutorialPopover } from "@/components/ui/tutorial-popover";
import { timeAgo } from "@/lib/utils";

export function TopBar() {
  const { data: fddStatus } = useFddStatus();
  const { data: config } = useConfig();
  const { theme, setTheme } = useTheme();
  const lastRun = fddStatus?.last_run;
  const isDark =
    theme === "dark" ||
    (theme === "system" && typeof document !== "undefined" && document.documentElement.classList.contains("dark"));
  const weatherEnabled = config?.open_meteo_enabled === true;
  const ruleIntervalHours = config?.rule_interval_hours as number | undefined;
  const withFdd = ruleIntervalHours != null && ruleIntervalHours > 0;
  const weatherTimeAgo = withFdd && lastRun?.run_ts ? timeAgo(lastRun.run_ts) : null;
  const standaloneIntervalHours = config?.open_meteo_interval_hours ?? 24;
  const weatherLabel = weatherTimeAgo
    ? weatherTimeAgo
    : withFdd
      ? ruleIntervalHours! < 1
        ? `with FDD (every ${Math.round(ruleIntervalHours! * 60)}m)`
        : `with FDD (every ${ruleIntervalHours}h)`
      : `every ${standaloneIntervalHours}h`;
  const weatherMeaning = withFdd
    ? "Weather is fetched with each FDD run."
    : "Weather is fetched by the standalone scraper every N hours.";

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border/60 bg-card/80 px-6 backdrop-blur-lg">
      <SiteSelector />
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        {lastRun ? (
          <TutorialPopover
            title="FDD run (Fault Detection & Diagnostics)"
            meaning="When the fault rule runner last executed. It evaluates your rules against timeseries data and updates fault state."
            status={`Last run ${timeAgo(lastRun.run_ts)}. ${lastRun.run_ts ? "Good." : "No runs yet."}`}
            side="bottom"
          >
            <span className="cursor-help">
              FDD run <span className="font-medium text-foreground">{timeAgo(lastRun.run_ts)}</span>
            </span>
          </TutorialPopover>
        ) : (
          <TutorialPopover
            title="FDD run"
            meaning="The fault rule runner has not completed a run yet. Start the fdd-loop service or trigger a run from the API."
            status="No FDD runs yet."
            side="bottom"
          >
            <span className="cursor-help">No FDD runs yet</span>
          </TutorialPopover>
        )}
        {weatherEnabled && (
          <TutorialPopover
            title="Weather"
            meaning={weatherMeaning}
            status={
              withFdd && lastRun?.run_ts
                ? "Fetched with last FDD run."
                : withFdd
                  ? "Fetched with each FDD run."
                  : `Standalone scraper every ${standaloneIntervalHours}h.`
            }
            side="bottom"
          >
            <span className="flex cursor-help items-center gap-1.5">
              <Cloud className="h-4 w-4" />
              Weather <span className="font-medium text-foreground">{weatherLabel}</span>
            </span>
          </TutorialPopover>
        )}
        <TutorialPopover
          title={isDark ? "Light mode" : "Dark mode"}
          meaning="Toggle between light and dark theme for the UI. Your preference is stored in the browser."
          status="Click to switch."
          side="bottom"
        >
          <button
            type="button"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </TutorialPopover>
      </div>
    </header>
  );
}
