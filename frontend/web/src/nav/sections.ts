/** Streamlit REQUIRED_MAIN_SECTIONS order (dashboard_contract.py). */
export const MAIN_SECTIONS = [
  { id: "overview", label: "Overview", path: "/" },
  { id: "data-model", label: "Data Model", path: "/mapping" },
  { id: "run-rules", label: "Run Rules", path: "/rules" },
  { id: "actions", label: "Actions", path: "/actions" },
  { id: "results", label: "Results by Category", path: "/findings" },
  { id: "fdd-plots", label: "FDD Plots", path: "/reports?section=fdd-plots" },
  { id: "rcx-plots", label: "RCx Plots", path: "/rcx" },
  { id: "metering", label: "Metering", path: "/metering" },
  { id: "wattlab", label: "WattLab", path: "/wattlab" },
] as const;

/** Primary React routes (Jobs vertical slice ahead of Streamlit wiring). */
export const SIDEBAR_NAV = [
  { to: "/", label: "Home", short: "H", testId: "nav-home" },
  { to: "/sites", label: "Sites", short: "S", testId: "nav-sites" },
  { to: "/auth", label: "Auth", short: "A", testId: "nav-auth" },
  { to: "/jobs", label: "Jobs", short: "J", testId: "nav-jobs" },
  { to: "/upload", label: "Upload", short: "U", testId: "nav-upload" },
  { to: "/mapping", label: "Mapping", short: "M", testId: "nav-mapping" },
  { to: "/rules", label: "Rules", short: "R", testId: "nav-rules" },
  { to: "/actions", label: "Actions", short: "X", testId: "nav-actions" },
  { to: "/findings", label: "Findings", short: "F", testId: "nav-findings" },
  { to: "/reports", label: "FDD Plots", short: "P", testId: "nav-reports" },
  { to: "/metering", label: "Metering", short: "E", testId: "nav-metering" },
  { to: "/wattlab", label: "WattLab", short: "W", testId: "nav-wattlab" },
  { to: "/twin", label: "Twin", short: "T", testId: "nav-twin" },
] as const;
