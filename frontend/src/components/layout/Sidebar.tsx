import { useState, useRef, useEffect } from "react";
import { Link, NavLink, useSearchParams } from "react-router-dom";
import {
  LayoutDashboard,
  Settings,
  CircleDot,
  AlertTriangle,
  LineChart,
  BarChart2,
  Cpu,
  Database,
  Search,
  Wrench,
  Sun,
  Moon,
  ChevronUp,
  LogOut,
  Radio,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useCapabilities, useHealth } from "@/hooks/use-fdd-status";
import { useActiveFaults } from "@/hooks/use-faults";
import { useTheme } from "@/contexts/theme-context";
import { useConfig } from "@/hooks/use-config";
import { timeAgo } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/config", label: "OpenFDD Config", icon: Settings, end: false },
  { to: "/bacnet-tools", label: "BACnet tools", icon: Radio, end: false },
  { to: "/data-model", label: "Data Model BRICK", icon: Database, end: false },
  { to: "/data-model-engineering", label: "Data Model Engineering", icon: Wrench, end: false },
  { to: "/data-model-testing", label: "Data Model Testing", icon: Search, end: false },
  { to: "/points", label: "Points", icon: CircleDot, end: false },
  { to: "/faults", label: "Faults", icon: AlertTriangle, end: false },
  { to: "/plots", label: "Plots", icon: LineChart, end: false },
  { to: "/weather", label: "Weather data", icon: Sun, end: false },
  { to: "/diagnostics", label: "Diagnostics", icon: BarChart2, end: false },
  { to: "/system", label: "System resources", icon: Cpu, end: false },
] as const;

const THEME_OPTIONS = [
  { value: "light" as const, icon: Sun, label: "Light" },
  { value: "dark" as const, icon: Moon, label: "Dark" },
];

export function Sidebar() {
  const [searchParams] = useSearchParams();
  const [healthOpen, setHealthOpen] = useState(false);
  const healthRef = useRef<HTMLDivElement>(null);
  const { data: capabilities } = useCapabilities();
  const { data: health } = useHealth();
  const { data: config } = useConfig();
  const { data: faults } = useActiveFaults();
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (healthRef.current && !healthRef.current.contains(e.target as Node)) {
        setHealthOpen(false);
      }
    }
    if (healthOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [healthOpen]);

  const isHealthy = health?.status === "ok";
  const gs = health?.graph_serialization;
  const lastFdd = health?.last_fdd_run;
  const ruleHours = config?.rule_interval_hours;
  const weatherWithFdd = config?.open_meteo_enabled === true && typeof ruleHours === "number" && ruleHours > 0;
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

      <div className="border-t border-border/60 px-3 py-2">
        <Link
          to="/logout"
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors duration-150 hover:bg-muted/40 hover:text-foreground"
        >
          <LogOut className="h-4 w-4 shrink-0" />
          <span>Sign out</span>
        </Link>
      </div>

      {/* Theme selector */}
      <div className="border-t border-border/60 px-5 py-3">
        <div className="flex items-center rounded-lg bg-muted/60 p-1">
          {THEME_OPTIONS.map(({ value, icon: Icon, label }) => {
            const isActive = theme === value || (theme === "system" && value === "light");
            return (
              <button
                key={value}
                type="button"
                aria-label={label}
                title={label}
                onClick={() => setTheme(value)}
                className={`flex flex-1 items-center justify-center rounded-md p-1.5 transition-colors duration-150 ${
                  isActive
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
              </button>
            );
          })}
        </div>
      </div>

      {/* Health indicator — click to open status details */}
      <div className="border-t border-border/60 px-5 py-3" ref={healthRef}>
        <button
          type="button"
          onClick={() => setHealthOpen(!healthOpen)}
          className="flex w-full items-center gap-2 text-xs text-left text-muted-foreground hover:text-foreground transition-colors"
          aria-expanded={healthOpen}
          aria-label="System status (click for details)"
        >
          <span
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${
              isHealthy
                ? "bg-success"
                : health
                  ? "bg-destructive"
                  : "bg-muted-foreground"
            }`}
            aria-hidden="true"
          />
          <span className="flex-1">
            {isHealthy
              ? "System healthy"
              : health
                ? "Unhealthy"
                : "Loading\u2026"}
          </span>
          <ChevronUp
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${healthOpen ? "" : "rotate-180"}`}
            aria-hidden="true"
          />
        </button>
        {healthOpen && health && (
          <div
            className="mt-2 rounded-lg border border-border/60 bg-card p-3 text-xs shadow-lg"
            role="dialog"
            aria-label="System status details"
          >
            <p className="font-medium text-foreground mb-2">Status</p>
            <ul className="space-y-2 text-muted-foreground">
              <li>
                <span className="font-medium text-foreground">API:</span>{" "}
                {health.status === "ok" ? "OK" : health.status}
              </li>
              {lastFdd?.run_ts && (
                <li>
                  <span className="font-medium text-foreground">Last FDD run:</span>{" "}
                  {timeAgo(lastFdd.run_ts)}
                  {weatherWithFdd && " (includes weather)"}
                  {lastFdd.sites_processed != null && ` · ${lastFdd.sites_processed} sites, ${lastFdd.faults_written ?? 0} faults`}
                </li>
              )}
              {gs && (
                <li>
                  <span className="font-medium text-foreground">RDF serialization:</span>{" "}
                  {gs.last_ok ? "OK" : "Error"}
                  {gs.last_serialization_at && ` · ${timeAgo(gs.last_serialization_at)}`}
                  {gs.last_error && (
                    <span className="block mt-0.5 text-destructive truncate" title={gs.last_error}>
                      {gs.last_error}
                    </span>
                  )}
                  {gs.path_resolved && (
                    <span className="block mt-0.5 text-muted-foreground/80 truncate" title={gs.path_resolved}>
                      {gs.path_resolved}
                    </span>
                  )}
                </li>
              )}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}
