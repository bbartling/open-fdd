import { NavLink, useSearchParams } from "react-router-dom";
import {
  LayoutDashboard,
  Server,
  CircleDot,
  AlertTriangle,
  TrendingUp,
  Cpu,
  Database,
  Sun,
  Moon,
  Monitor,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useCapabilities, useHealth } from "@/hooks/use-fdd-status";
import { useActiveFaults } from "@/hooks/use-faults";
import { useTheme } from "@/contexts/theme-context";

const NAV_ITEMS = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/equipment", label: "Equipment", icon: Server, end: false },
  { to: "/points", label: "Points", icon: CircleDot, end: false },
  { to: "/faults", label: "Faults", icon: AlertTriangle, end: false },
  { to: "/trending", label: "Trending", icon: TrendingUp, end: false },
  { to: "/system", label: "System resources", icon: Cpu, end: false },
  { to: "/data-model", label: "Data model", icon: Database, end: false },
] as const;

const THEME_OPTIONS = [
  { value: "system" as const, icon: Monitor, label: "System" },
  { value: "light" as const, icon: Sun, label: "Light" },
  { value: "dark" as const, icon: Moon, label: "Dark" },
];

export function Sidebar() {
  const [searchParams] = useSearchParams();
  const { data: capabilities } = useCapabilities();
  const { data: health } = useHealth();
  const { data: faults } = useActiveFaults();
  const { theme, setTheme } = useTheme();

  const isHealthy = health?.status === "ok";
  const siteParam = searchParams.get("site");
  const search = siteParam ? `?site=${siteParam}` : "";

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border/60 bg-card/50">
      {/* Branding */}
      <div className="flex items-center gap-2.5 border-border/60 px-5 py-4">
        <span className="text-lg font-semibold tracking-tight text-foreground">
          Open-FDD
        </span>
        {capabilities && (
          <Badge variant="outline" className="text-[10px]">
            v{capabilities.version}
          </Badge>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3 py-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={{ pathname: to, search }}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150 ${
                isActive
                  ? "bg-muted/70 font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
              }`
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span>{label}</span>
            {label === "Faults" && faults && faults.length > 0 && (
              <Badge
                variant="destructive"
                className="ml-auto h-5 min-w-5 justify-center px-1.5 text-[10px]"
              >
                {faults.length}
              </Badge>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Theme selector */}
      <div className="border-t border-border/60 px-5 py-3">
        <div className="flex items-center rounded-lg bg-muted/60 p-1">
          {THEME_OPTIONS.map(({ value, icon: Icon, label }) => (
            <button
              key={value}
              type="button"
              aria-label={label}
              title={label}
              onClick={() => setTheme(value)}
              className={`flex flex-1 items-center justify-center rounded-md p-1.5 transition-colors duration-150 ${
                theme === value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>
      </div>

      {/* Health indicator */}
      <div className="border-t border-border/60 px-5 py-3">
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              isHealthy
                ? "bg-success"
                : health
                  ? "bg-destructive"
                  : "bg-muted-foreground"
            }`}
            aria-hidden="true"
          />
          <span className="text-muted-foreground">
            {isHealthy
              ? "System healthy"
              : health
                ? "Unhealthy"
                : "Loading\u2026"}
          </span>
        </div>
      </div>
    </aside>
  );
}
