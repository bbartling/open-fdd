import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, hasToken } from "../../lib/api";
import type {
  DashboardAnalytics,
  DashboardSummary,
  FddRulesResponse,
} from "../../lib/dashboardSummaryTypes";
import type { InsightResponse } from "../../lib/insightTypes";

type BuildingMeta = {
  ok?: boolean;
  model_score?: number | null;
  model_counts?: {
    equipment?: number;
    points?: number;
    mapped_points?: number;
    unmapped_points?: number;
  };
  alert_count?: number;
  rule_count?: number;
  datafusion_ok?: boolean;
};

type Props = {
  refreshKey?: number;
  insight?: InsightResponse | null;
  insightError?: string;
  buildingMeta?: BuildingMeta | null;
};

function formatProtocolLabel(protocol: string): string {
  switch (protocol) {
    case "json_api":
      return "JSON API";
    case "csv_import":
      return "CSV import";
    default:
      return protocol.replace(/_/g, " ");
  }
}

export default function OperationalContextPanel({
  refreshKey,
  insight,
  insightError,
  buildingMeta,
}: Props) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [analytics, setAnalytics] = useState<DashboardAnalytics | null>(null);
  const [rules, setRules] = useState<FddRulesResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const signedIn = hasToken();

  useEffect(() => {
    if (!signedIn) {
      setSummary(null);
      setAnalytics(null);
      setRules(null);
      setLoadError("");
      return;
    }
    let cancelled = false;
    setLoadError("");
    Promise.all([
      apiFetch<DashboardSummary>("/api/dashboard/summary"),
      apiFetch<DashboardAnalytics>("/api/dashboard/analytics"),
      apiFetch<FddRulesResponse>("/api/fdd-rules"),
    ])
      .then(([s, a, r]) => {
        if (cancelled) return;
        setSummary(s);
        setAnalytics(a);
        setRules(r);
      })
      .catch((e) => {
        if (cancelled) return;
        setSummary(null);
        setAnalytics(null);
        setRules(null);
        setLoadError(e instanceof Error ? e.message : "Could not load operational context");
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey, signedIn]);

  const model = summary?.model_coverage;
  const ruleHealth = analytics?.rule_health;
  const ruleList = rules?.rules ?? [];
  const enabledRules = ruleList.filter((r) => r.enabled !== false);
  const ruleCount =
    ruleHealth?.rule_count ?? ruleList.length ?? buildingMeta?.rule_count ?? 0;
  const activeFaults = summary?.faults?.active_count ?? buildingMeta?.alert_count ?? 0;
  const historian = summary?.historian_health;

  const mappedSources = useMemo(() => {
    const fromHealth =
      summary?.source_health?.sources?.filter((s) => (s.point_count ?? 0) > 0) ?? [];
    if (fromHealth.length) {
      return fromHealth.map((s) => ({
        label: formatProtocolLabel(s.protocol ?? "unknown"),
        count: s.point_count ?? 0,
        status: s.status ?? (s.enabled ? "ready" : "disabled"),
      }));
    }
    return (analytics?.source_coverage?.protocols ?? [])
      .filter((p) => (p.point_count ?? 0) > 0 && p.protocol !== "unmapped")
      .map((p) => ({
        label: formatProtocolLabel(p.protocol ?? "unknown"),
        count: p.point_count ?? 0,
        status: "mapped",
      }));
  }, [summary, analytics]);

  const modelLine =
    model && (model.equipment_count ?? 0) + (model.point_count ?? 0) > 0
      ? `${model.equipment_count ?? 0} equipment · ${model.point_count ?? 0} points · ${model.mapped_points ?? 0} mapped${
          (model.unmapped_points ?? 0) > 0 ? ` · ${model.unmapped_points} unmapped` : ""
        }${model.model_score != null ? ` · ${model.model_score}% coverage` : ""}`
      : buildingMeta?.model_counts &&
          ((buildingMeta.model_counts.equipment ?? 0) > 0 ||
            (buildingMeta.model_counts.points ?? 0) > 0)
        ? `${buildingMeta.model_counts.equipment ?? 0} equipment · ${buildingMeta.model_counts.points ?? 0} points · ${buildingMeta.model_counts.mapped_points ?? 0} mapped${
            (buildingMeta.model_counts.unmapped_points ?? 0) > 0
              ? ` · ${buildingMeta.model_counts.unmapped_points} unmapped`
              : ""
          }${buildingMeta.model_score != null ? ` · ${buildingMeta.model_score}% coverage` : ""}`
        : "No Haystack model loaded — sign in and import under Model & assignments.";

  const rulesLine =
    ruleCount > 0
      ? `${enabledRules.length || ruleCount} FDD rule${ruleCount === 1 ? "" : "s"} configured${
          (ruleHealth?.datafusion_ok ?? buildingMeta?.datafusion_ok) === false
            ? " · DataFusion check failed"
            : ""
        }`
      : signedIn
        ? "No FDD rules configured — add rules under SQL FDD."
        : "Sign in to view FDD rule configuration.";

  const faultLine =
    activeFaults === 0
      ? "No active faults."
      : `${activeFaults} active fault${activeFaults === 1 ? "" : "s"} in historian evaluation.`;

  const historianLine = historian
    ? `${historian.row_count ?? 0} historian rows${
        historian.latest_sample_at ? ` · latest ${historian.latest_sample_at}` : ""
      }${historian.subdir_count ? ` · ${historian.subdir_count} partition(s)` : ""}`
    : signedIn
      ? "Historian status unavailable."
      : "Sign in for historian row counts and validation profile details.";

  const validationProfile = summary?.validation?.profile_id;
  const feeds = insight?.brick_model?.feeds_chains ?? [];

  return (
    <div className="bis-card">
      <h3>Context</h3>
      <h2>Data model &amp; FDD</h2>
      <p className="bis-muted-line">
        <strong>Model:</strong> {modelLine}{" "}
        <Link to="/model" className="bis-inline-link">
          Model
        </Link>
      </p>
      {mappedSources.length ? (
        <p className="bis-muted-line">
          <strong>Mapped sources:</strong>{" "}
          {mappedSources.map((s) => `${s.label} (${s.count})`).join(" · ")}
        </p>
      ) : (
        <p className="muted">No protocol-mapped points yet.</p>
      )}
      <p className="bis-muted-line">
        <strong>Rules:</strong> {rulesLine}{" "}
        <Link to="/sql-fdd" className="bis-inline-link">
          SQL FDD
        </Link>
      </p>
      {enabledRules.length ? (
        <p className="bis-muted-line">
          <strong>Active rules:</strong>{" "}
          {enabledRules
            .slice(0, 6)
            .map((r) => r.name || r.id || "rule")
            .join(", ")}
          {enabledRules.length > 6 ? " …" : ""}
        </p>
      ) : null}
      <p className="bis-muted-line">
        <strong>Faults:</strong> {faultLine}
      </p>
      <p className="bis-muted-line">
        <strong>Historian:</strong> {historianLine}
      </p>
      {validationProfile ? (
        <p className="bis-muted-line">
          <strong>Validation profile:</strong> {validationProfile}
          {summary?.validation?.live_fdd_pass &&
          summary.validation.live_fdd_pass !== "unknown"
            ? ` · last pass ${summary.validation.live_fdd_pass}`
            : ""}
        </p>
      ) : null}

      {feeds.length ? (
        <>
          <h3 className="bis-subhead">Feeds &amp; research</h3>
          <p className="bis-muted-line">
            <strong>Haystack feeds:</strong> {feeds.slice(0, 5).join("; ")}
            {feeds.length > 5 ? " …" : ""}
          </p>
        </>
      ) : null}
      {insight?.zone_temps?.struggling_zones?.length ? (
        <p className="bis-muted-line">
          <strong>Slow recovery:</strong>{" "}
          {insight.zone_temps.struggling_zones
            .slice(0, 4)
            .map((z) => `${z.label || "?"} (${z.ahu_name || "AHU"})`)
            .join(", ")}
        </p>
      ) : null}
      {insight?.faults_linked?.length ? (
        <ul className="bis-linked-faults">
          {insight.faults_linked.slice(0, 6).map((f) => (
            <li key={`${f.code}-${f.equipment_name}`}>
              <span className="bis-code">{f.code}</span> {f.title}
              {f.equipment_name ? ` · ${f.equipment_name}` : ""}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="bis-foot-meta">
        Rule-based summary from bridge APIs
        {insight?.source === "ollama" ? " · insight agent available" : ""}
        {insight?.generated_at != null
          ? ` · insight ${new Date(insight.generated_at * 1000).toLocaleString()}`
          : ""}
      </p>
      {insight?.error && !insight.ollama_ok ? (
        <p className="muted">Ollama offline — operational context above is from live APIs.</p>
      ) : null}
      {loadError ? <p className="error">{loadError}</p> : null}
      {insightError ? <p className="error">{insightError}</p> : null}
    </div>
  );
}
