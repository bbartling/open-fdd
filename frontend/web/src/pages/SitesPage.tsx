import { Navigate, useSearchParams } from "react-router";

/** Legacy `/sites` — site inventory now lives under Operations → Sites. */
export function SitesPage() {
  const [params] = useSearchParams();
  const next = new URLSearchParams(params);
  next.set("view", "sites");
  return <Navigate to={`/operations?${next.toString()}`} replace />;
}
