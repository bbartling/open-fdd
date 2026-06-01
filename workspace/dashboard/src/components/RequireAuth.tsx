import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { fetchAuthStatus, hasToken, setToken } from "../lib/api";

/** Gate integrator/agent pages. Check-engine home + fault catalog stay public. */
export default function RequireAuth() {
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);

  useEffect(() => {
    fetchAuthStatus()
      .then((s) => {
        setAuthRequired(s.auth_required);
        if (!s.auth_required) setToken("open");
      })
      .catch(() => setAuthRequired(true));
  }, []);

  if (authRequired === null) return <p className="muted">Loading…</p>;
  if (authRequired && !hasToken()) return <Navigate to="/login" replace />;
  return <Outlet />;
}
