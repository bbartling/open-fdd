import { Sun, Moon, Cloud } from "lucide-react";
import { SiteSelector } from "./SiteSelector";
import { useFddStatus } from "@/hooks/use-fdd-status";
import { useConfig } from "@/hooks/use-config";
import { useTheme } from "@/contexts/theme-context";
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
  const weatherInterval = config?.open_meteo_interval_hours;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border/60 bg-card/80 px-6 backdrop-blur-lg">
      <SiteSelector />
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        {lastRun ? (
          <span title="Fault rule runner last ran">
            FDD run <span className="font-medium text-foreground">{timeAgo(lastRun.run_ts)}</span>
          </span>
        ) : (
          <span>No FDD runs yet</span>
        )}
        {weatherEnabled && (
          <span className="flex items-center gap-1.5" title="Weather fetcher">
            <Cloud className="h-4 w-4" />
            Weather {weatherInterval != null ? `every ${weatherInterval}h` : "on"}
          </span>
        )}
        <button
          type="button"
          onClick={() => setTheme(isDark ? "light" : "dark")}
          className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          title={isDark ? "Light mode" : "Dark mode"}
        >
          {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}
