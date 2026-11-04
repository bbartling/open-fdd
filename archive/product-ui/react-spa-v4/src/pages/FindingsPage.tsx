import { Navigate, useSearchParams } from "react-router";

/**
 * Legacy `/findings` path — Results by Category now lives under Data Model
 * (`/mapping?view=results`).
 */
export function FindingsPage() {
  const [params] = useSearchParams();
  const next = new URLSearchParams(params);
  next.set("view", "results");
  return <Navigate to={`/mapping?${next.toString()}`} replace />;
}
