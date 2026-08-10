import { useLocation, useNavigate, useSearchParams } from "react-router";
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
  if (pathname.startsWith("/wattlab") || pathname.startsWith("/twin")) {
    return "wattlab";
  }
  if (pathname.startsWith("/mapping")) return "data-model";
  if (pathname.startsWith("/sites")) return "sites";
  if (pathname.startsWith("/actions")) return "actions";
  if (pathname.startsWith("/findings")) return "results";
  if (pathname.startsWith("/rcx")) return "rcx-plots";
  if (pathname.startsWith("/metering")) return "metering";
  if (pathname === "/" || pathname === "") return "overview";
  if (pathname.startsWith("/reports")) {
    if (searchSection === "rcx-plots") return "rcx-plots";
    if (searchSection === "metering") return "metering";
    return "fdd-plots";
  }
  return null;
}

function sectionPath(id: string, fallback: string): string {
  switch (id) {
    case "fdd-plots":
      return "/reports?section=fdd-plots";
    case "rcx-plots":
      return "/rcx";
    case "metering":
      return "/metering";
    case "actions":
      return "/actions";
    default:
      return fallback;
  }
}

/** Streamlit-style horizontal radio section selector. */
export function SectionTabs({ activeSectionId }: SectionTabsProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const active = resolveActiveId(
    location.pathname,
    params.get("section"),
    activeSectionId,
  );

  return (
    <fieldset
      className="app-section-tabs"
      aria-label="Main sections"
      data-testid="section-tabs"
    >
      <legend className="app-section-tabs__legend">Section</legend>
      {MAIN_SECTIONS.map((section) => {
        const isActive = active === section.id;
        const to = sectionPath(section.id, section.path);
        return (
          <label
            key={section.id}
            className={`app-section-tabs__radio${isActive ? " app-section-tabs__radio--active" : ""}`}
            data-testid={`section-${section.id}`}
            data-section={section.id}
          >
            <input
              type="radio"
              name="main-section"
              value={section.id}
              checked={isActive}
              onChange={() => navigate(to)}
            />
            <span>{section.label}</span>
          </label>
        );
      })}
    </fieldset>
  );
}
