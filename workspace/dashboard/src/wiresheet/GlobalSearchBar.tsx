import { useMemo, useState } from "react";
import type { Node } from "@xyflow/react";

type Props = {
  nodes: Node[];
  onFocusNode: (nodeId: string) => void;
};

const SCOPES = ["All", "Equipment", "Points", "Rules", "SQL", "Faults", "Tags", "CSV"] as const;

export default function GlobalSearchBar({ nodes, onFocusNode }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<(typeof SCOPES)[number]>("All");

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return nodes.filter((n) => {
      const data = n.data as { label?: string; nodeType?: string; config?: Record<string, unknown> };
      const hay = [
        data.label,
        data.nodeType,
        JSON.stringify(data.config ?? {}),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
      if (scope === "All") return true;
      if (scope === "Rules") return (data.nodeType ?? "").includes("sql");
      if (scope === "Faults") return (data.nodeType ?? "").includes("fault");
      if (scope === "Points") return (data.nodeType ?? "").includes("point");
      if (scope === "Equipment") return (data.nodeType ?? "").includes("equip");
      if (scope === "SQL") return hay.includes("sql");
      if (scope === "Tags") return hay.includes("tag");
      if (scope === "CSV") return hay.includes("csv");
      return true;
    });
  }, [nodes, query, scope]);

  return (
    <div className="wiresheet-search" role="search">
      <select
        aria-label="Search scope"
        value={scope}
        onChange={(e) => setScope(e.target.value as (typeof SCOPES)[number])}
      >
        {SCOPES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <input
        type="search"
        placeholder="Search equipment, points, rules, SQL…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Global wiresheet search"
      />
      {query && results.length > 0 ? (
        <ul className="wiresheet-search__results">
          {results.slice(0, 8).map((n) => {
            const data = n.data as { label?: string; nodeType?: string };
            return (
              <li key={n.id}>
                <button type="button" onClick={() => onFocusNode(n.id)}>
                  <strong>{data.label}</strong>
                  <span className="muted"> {data.nodeType}</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
