import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";

type Code = {
  code: string;
  category: string;
  title: string;
  severity: string;
  description: string;
  likely_causes: string[];
  suggested_checks: string[];
  cookbook_patterns?: string[];
};

type CategoryNode = { category: string; label: string; codes: Code[] };
type FamilyNode = { family: string; label: string; description: string; categories: CategoryNode[] };

type AssignedRule = {
  rule_id: string;
  rule_name: string;
  fault_code: string;
  family: string;
  severity: string;
};

type EquipmentHit = { equipment_id: string; name: string; equipment_type: string };

type ApplicableTree = {
  version: number;
  site_id: string;
  model_configured: boolean;
  query_engine: string;
  equipment_count: number;
  applicable_families: string[];
  hidden_families: string[];
  family_equipment: Record<string, EquipmentHit[]>;
  unmatched_equipment: EquipmentHit[];
  assigned_rules: AssignedRule[];
  families: FamilyNode[];
};

type SiteRow = { site_id: string; name: string };

const SEV_CLASS: Record<string, string> = {
  critical: "alert-critical",
  warning: "alert-warning",
  info: "alert-info",
};

function FamilyPanel({ fam }: { fam: FamilyNode }) {
  return (
    <div className="panel">
      <h3 className="panel-title">
        {fam.label} <span className="badge">{fam.family}</span>
      </h3>
      <p className="muted">{fam.description}</p>
      {fam.categories.map((cat) => (
        <details key={cat.category} className="fault-family">
          <summary>
            <strong>{cat.label}</strong>
            <span className="badge">{cat.codes.length}</span>
          </summary>
          <table className="fault-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Fault</th>
                <th>Cookbook</th>
                <th>Likely causes</th>
                <th>Suggested checks</th>
              </tr>
            </thead>
            <tbody>
              {cat.codes.map((c) => (
                <tr key={c.code} className={SEV_CLASS[c.severity] || ""}>
                  <td>
                    <span className="badge code-badge">{c.code}</span>
                  </td>
                  <td>
                    <strong>{c.title}</strong>
                    <div className="muted">{c.description}</div>
                  </td>
                  <td className="muted">{(c.cookbook_patterns || []).join(", ") || "—"}</td>
                  <td className="muted">{c.likely_causes.join("; ")}</td>
                  <td className="muted">{c.suggested_checks.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </div>
  );
}

export default function FaultsPage() {
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [siteId, setSiteId] = useState("");
  const [tree, setTree] = useState<ApplicableTree | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState("");
  const [validationError, setValidationError] = useState("");

  const loadScope = useCallback(async (sid: string) => {
    setLoading(true);
    setError("");
    try {
      const q = sid ? `?site_id=${encodeURIComponent(sid)}` : "";
      const res = await apiFetch<ApplicableTree>(`/api/faults/applicable${q}`);
      setTree(res);
      if (!sid && res.site_id) setSiteId(res.site_id);
    } catch (e) {
      setError(String(e));
      setTree(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    apiFetch<{ sites: SiteRow[]; active_site_id?: string }>("/api/model/sites")
      .then((res) => {
        const list = res.sites ?? [];
        setSites(list);
        const initial = res.active_site_id || list[0]?.site_id || "";
        if (initial) {
          setSiteId(initial);
          void loadScope(initial);
        } else {
          void loadScope("");
        }
      })
      .catch(() => void loadScope(""));
  }, [loadScope]);

  async function validateWithOllama() {
    setValidating(true);
    setValidation("");
    setValidationError("");
    try {
      const res = await apiFetch<{ ok: boolean; validation?: string; ollama_error?: string }>(
        "/api/faults/validate-scope",
        {
          method: "POST",
          body: JSON.stringify({ site_id: siteId || tree?.site_id }),
        },
      );
      if (res.validation) setValidation(res.validation);
      if (!res.ok && res.ollama_error) setValidationError(res.ollama_error);
    } catch (e) {
      setValidationError(String(e));
    } finally {
      setValidating(false);
    }
  }

  const hidden = tree?.hidden_families ?? [];

  return (
    <div className="page page-wide">
      <PageHeader
        title="Fault catalog"
        subtitle={
          <>
            Scoped to your BRICK data model via SPARQL — only families that match modeled equipment (AHU, VAV/FCU,
            heat pump, chiller, …) are shown. Assigned Rule Lab rules with catalog codes appear below. Ollama validates
            scope against the live model.
          </>
        }
      />

      <div className="panel">
        <div className="form-row">
          <div className="field">
            <label className="field-label" htmlFor="fault-site">
              Site
            </label>
            <select
              id="fault-site"
              value={siteId}
              onChange={(e) => {
                setSiteId(e.target.value);
                void loadScope(e.target.value);
              }}
            >
              {!sites.length ? <option value="">Default site</option> : null}
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>
                  {s.name} ({s.site_id})
                </option>
              ))}
            </select>
          </div>
          <div className="form-row-actions">
            <button type="button" className="secondary-btn" disabled={loading} onClick={() => void loadScope(siteId)}>
              Refresh scope
            </button>
            <button
              type="button"
              className="secondary-btn"
              disabled={validating || !tree?.model_configured}
              onClick={() => void validateWithOllama()}
            >
              {validating ? "Validating…" : "Validate with Ollama"}
            </button>
          </div>
        </div>
        {tree ? (
          <div className="status-bar">
            <div className="status-kv">
              <span className="status-kv-label">Query</span>
              <span className="status-kv-value">
                <code>{tree.query_engine}</code> — {tree.equipment_count} equipment
              </span>
            </div>
            <div className="status-kv">
              <span className="status-kv-label">Applicable</span>
              <span className="status-kv-value">{tree.applicable_families.join(", ") || "—"}</span>
            </div>
            {hidden.length ? (
              <div className="status-kv">
                <span className="status-kv-label">Hidden</span>
                <span className="status-kv-value muted">{hidden.join(", ")}</span>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <Spinner label="Loading model-scoped catalog…" /> : null}

      {!loading && tree && !tree.model_configured ? (
        <div className="panel">
          <p className="muted">
            No BRICK equipment found for this site. Import or model equipment on{" "}
            <Link to="/model">Model & assignments</Link> commissioning JSON to pin rules to points.
          </p>
        </div>
      ) : null}

      {!loading && tree?.assigned_rules?.length ? (
        <div className="panel">
          <h3 className="panel-title">Assigned rules (this site)</h3>
          <table className="fault-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Fault code</th>
                <th>Family</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {tree.assigned_rules.map((r) => (
                <tr key={r.rule_id}>
                  <td>
                    <Link to="/model">{r.rule_name}</Link>
                  </td>
                  <td>
                    <span className="badge code-badge">{r.fault_code}</span>
                  </td>
                  <td>{r.family}</td>
                  <td>{r.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {validation ? (
        <div className="panel">
          <h3 className="panel-title">Ollama validation</h3>
          <p>{validation}</p>
        </div>
      ) : null}
      {validationError ? <p className="muted">Ollama: {validationError}</p> : null}

      {!loading && tree?.unmatched_equipment?.length ? (
        <details className="panel fault-family">
          <summary>
            <strong>Unmatched equipment</strong>
            <span className="badge">{tree.unmatched_equipment.length}</span>
            <span className="muted" style={{ marginLeft: 8 }}>
              — no catalog family (set BRICK equipment_type on Data Model)
            </span>
          </summary>
          <ul>
            {tree.unmatched_equipment.map((eq) => (
              <li key={eq.equipment_id}>
                <code>{eq.equipment_type || "unknown"}</code> — {eq.name}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {!loading && tree?.families?.length
        ? tree.families.map((fam) => (
            <div key={fam.family}>
              {tree.family_equipment?.[fam.family]?.length ? (
                <p className="muted" style={{ margin: "0 0 8px 4px" }}>
                  Equipment:{" "}
                  {tree.family_equipment[fam.family].map((e) => e.name).join(", ")}
                </p>
              ) : null}
              <FamilyPanel fam={fam} />
            </div>
          ))
        : null}

      {!loading && tree?.model_configured && !tree.families.length ? (
        <p className="muted">No applicable fault families for modeled equipment types.</p>
      ) : null}
    </div>
  );
}
