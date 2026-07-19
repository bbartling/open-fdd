import { Link, Outlet, useNavigate } from "react-router-dom";
import { useTheme } from "../contexts/theme-context";
import { clearToken, hasToken } from "../lib/api";

/** Minimal chrome for the Streamlit-parity Lab.
 *
 * The product navigation intentionally does not wrap `/lab`: vibe19 is one
 * focused workspace with one data/tuning rail, not two competing sidebars.
 */
export default function LabShell() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="lab-app-shell">
      <div className="lab-app-controls" aria-label="Lab controls">
        <Link to="/" className="lab-product-link">
          Open-FDD product
        </Link>
        <button type="button" className="secondary-btn" onClick={toggleTheme}>
          {theme === "dark" ? "Light UI" : "Dark UI"}
        </button>
        {hasToken() ? (
          <button
            type="button"
            className="secondary-btn"
            onClick={() => {
              clearToken();
              navigate("/login");
            }}
          >
            Sign out
          </button>
        ) : null}
      </div>
      <Outlet />
    </div>
  );
}
