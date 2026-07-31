import { NavLink, useLocation, useSearchParams } from "react-router";
import { MAIN_SECTIONS } from "../nav/sections";

interface SectionTabsProps {
  activeSectionId?: string;
}

function resolveActiveId(
  pathname: string,
  searchSection: string | null,
  override?: string,
): string | null {
  if (override) return override;
  if (pathname.startsWith("/wattlab")) return "wattlab";
  if (pathname.startsWith("/mapping")) return "data-model";
  if (pathname.startsWith("/rules")) return "run-rules";
  if (pathname.startsWith("/findings")) return "results";
  if (pathname === "/" || pathname === "") return "overview";
  if (pathname.startsWith("/reports")) {
    if (searchSection === "rcx-plots") return "rcx-plots";
    if (searchSection === "metering") return "metering";
    return "fdd-plots";
  }
  return null;
}

export function SectionTabs({ activeSectionId }: SectionTabsProps) {
  const location = useLocation();
  const [params] = useSearchParams();
  const active = resolveActiveId(
    location.pathname,
    params.get("section"),
    activeSectionId,
  );

  return (
    <nav
      className="app-section-tabs"
      aria-label="Main sections"
      data-testid="section-tabs"
    >
      {MAIN_SECTIONS.map((section) => {
        const to =
          section.id === "fdd-plots"
            ? "/reports?section=fdd-plots"
            : section.id === "rcx-plots"
              ? "/reports?section=rcx-plots"
              : section.id === "metering"
                ? "/reports?section=metering"
                : section.path;
        const isActive = active === section.id;

        return (
          <NavLink
            key={section.id}
            to={to}
            className={() =>
              `app-section-tabs__tab${isActive ? " app-section-tabs__tab--active" : ""}`
            }
            data-testid={`section-${section.id}`}
            data-section={section.id}
            aria-current={isActive ? "page" : undefined}
          >
            {section.label}
          </NavLink>
        );
      })}
    </nav>
  );
}
