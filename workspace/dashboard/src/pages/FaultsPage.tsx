import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import PageHeader from "../components/PageHeader";

type Code = {
  code: string;
  category: string;
  title: string;
  severity: string;
  description: string;
  likely_causes: string[];
  suggested_checks: string[];
  cookbook_patterns?: string[];
  suffix?: string;
};

type CategoryNode = { category: string; label: string; codes: Code[] };
type FamilyNode = { family: string; label: string; description: string; categories: CategoryNode[] };
type Tree = { version: number; families: FamilyNode[] };

const SEV_CLASS: Record<string, string> = {
  critical: "alert-critical",
  warning: "alert-warning",
  info: "alert-info",
};

export default function FaultsPage() {
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<Tree>("/api/faults/tree").then(setTree).catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="page page-wide">
      <PageHeader
        title="Building fault catalog"
        subtitle={
          <>
            Letter-suffix codes (e.g. <strong>VAV-C</strong>, <strong>AHU-B</strong>) — not numeric tags like
            VAV-03 that collide with equipment names on retrofit sites. Each code links to FDD categories and Rule Lab
            cookbook patterns. The Ollama agent and building insight use this catalog only.
          </>
        }
      />

      {error ? <p className="muted">Could not load catalog: {error}</p> : null}
      {!tree && !error ? (
        <p className="muted">Loading catalog…</p>
      ) : tree ? (
        tree.families.map((fam) => (
          <div key={fam.family} className="panel">
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
        ))
      ) : null}
    </div>
  );
}
