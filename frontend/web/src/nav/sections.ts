/** Product main section tabs (horizontal radio selector). */
export const MAIN_SECTIONS = [
  { id: "overview", label: "Overview", path: "/" },
  { id: "inspect", label: "Inspect", path: "/inspect" },
  { id: "data-model", label: "Data Model", path: "/mapping" },
  { id: "actions", label: "Actions", path: "/actions" },
  { id: "results", label: "Results by Category", path: "/findings" },
  { id: "fdd-plots", label: "FDD Plots", path: "/reports?section=fdd-plots" },
  { id: "rcx-plots", label: "RCx Plots", path: "/rcx" },
  { id: "metering", label: "Metering", path: "/metering" },
  { id: "export", label: "Dump", path: "/export" },
  { id: "sites", label: "Sites", path: "/sites" },
  { id: "operations", label: "Operations", path: "/operations" },
] as const;

/** Secondary App pages (collapsed sidebar details). */
export const SIDEBAR_NAV = [
  { to: "/", label: "Home", short: "H", testId: "nav-home" },
  { to: "/auth", label: "Auth", short: "A", testId: "nav-auth" },
  { to: "/jobs", label: "Jobs", short: "J", testId: "nav-jobs" },
  { to: "/upload", label: "Upload", short: "U", testId: "nav-upload" },
  { to: "/mapping", label: "Mapping", short: "M", testId: "nav-mapping" },
  { to: "/actions", label: "Actions", short: "X", testId: "nav-actions" },
  { to: "/findings", label: "Findings", short: "F", testId: "nav-findings" },
  { to: "/reports", label: "FDD Plots", short: "P", testId: "nav-reports" },
  { to: "/metering", label: "Metering", short: "E", testId: "nav-metering" },
  { to: "/export", label: "Dump", short: "X", testId: "nav-export" },
  { to: "/twin", label: "Twin", short: "T", testId: "nav-twin" },
  { to: "/operations", label: "Operations", short: "O", testId: "nav-operations" },
] as const;
