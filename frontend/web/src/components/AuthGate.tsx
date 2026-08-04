import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router";
import {
  getAuthMe,
  getAuthStatus,
  getStoredToken,
  logout,
} from "../api/authApi";

/**
 * When central has auth_required, block the app until a session token exists.
 * /auth stays outside this gate so login remains reachable.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [state, setState] = useState<"loading" | "ok" | "need-login">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const status = await getAuthStatus();
        if (!status.auth_required) {
          if (!cancelled) setState("ok");
          return;
        }
        if (!getStoredToken()) {
          if (!cancelled) setState("need-login");
          return;
        }
        try {
          await getAuthMe();
          if (!cancelled) setState("ok");
        } catch {
          logout();
          if (!cancelled) setState("need-login");
        }
      } catch {
        // Status probe failed — do not hard-lock the shell.
        if (!cancelled) setState("ok");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  if (state === "loading") {
    return (
      <div className="page-stack" data-testid="auth-gate-loading">
        Checking session…
      </div>
    );
  }

  if (state === "need-login") {
    const from = `${location.pathname}${location.search}`;
    return (
      <Navigate
        to={`/auth?from=${encodeURIComponent(from)}`}
        replace
      />
    );
  }

  return children;
}
