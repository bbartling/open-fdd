import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type GraphPoint = {
  point_id: string;
  name?: string;
  label?: string;
  brick_type?: string;
  timeseries_column?: string;
  fdd_input?: string;
  series_id?: string;
};

type GraphEquipment = {
  equipment_id: string;
  name?: string;
  label?: string;
  equipment_type?: string;
  brick_type?: string;
  bacnet_device_instance?: number | string;
};

type FeedEdge = {
  from_equipment_id: string;
  to_equipment_id: string;
  from_label?: string;
  to_label?: string;
};

type ModelGraph = {
  site_id: string;
  query_engine?: string;
  equipment: GraphEquipment[];
  feeds: FeedEdge[];
  points_by_equipment: Record<string, GraphPoint[]>;
};

type ContextTarget =
  | { kind: "point"; id: string; label: string }
  | { kind: "equipment"; id: string; label: string };

type Props = {
  siteId?: string;
  onStatus?: (msg: string) => void;
  refreshKey?: number;
  onModelChange?: () => void;
};

function eqLabel(eq: GraphEquipment): string {
  return String(eq.label || eq.name || eq.equipment_id);
}

function pointLabel(p: GraphPoint): string {
  return String(p.label || p.name || p.timeseries_column || p.point_id);
}

export default function ModelGraphExplorer({ siteId, onStatus, refreshKey = 0, onModelChange }: Props) {
  const [graph, setGraph] = useState<ModelGraph | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState<(ContextTarget & { x: number; y: number }) | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const q = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
    const data = await apiFetch<ModelGraph>(`/api/model/graph${q}`);
    setGraph(data);
    setError("");
  }, [siteId]);

  useEffect(() => {
    load().catch((e) => setError(formatApiError(e)));
  }, [load, refreshKey]);

  useEffect(() => {
    function closeMenu() {
      setMenu(null);
    }
    window.addEventListener("click", closeMenu);
    window.addEventListener("scroll", closeMenu, true);
    return () => {
      window.removeEventListener("click", closeMenu);
      window.removeEventListener("scroll", closeMenu, true);
    };
  }, []);

  const orderedEquipment = useMemo(() => {
    if (!graph?.equipment?.length) return [];
    const eq = graph.equipment;
    const byId = new Map(eq.map((e) => [e.equipment_id, e]));
    const fedBy = new Map<string, string[]>();
    for (const edge of graph.feeds || []) {
      const src = edge.from_equipment_id;
      if (!fedBy.has(src)) fedBy.set(src, []);
      fedBy.get(src)!.push(edge.to_equipment_id);
    }
    const seen = new Set<string>();
    const out: GraphEquipment[] = [];
    const sources = eq.filter((e) => (graph.feeds || []).some((f) => f.from_equipment_id === e.equipment_id));
    const roots = sources.length ? sources : eq.filter((e) => !eq.some((x) => (fedBy.get(x.equipment_id) || []).includes(e.equipment_id)));
    const queue = [...roots];
    while (queue.length) {
      const cur = queue.shift()!;
      if (seen.has(cur.equipment_id)) continue;
      seen.add(cur.equipment_id);
      out.push(cur);
      for (const childId of fedBy.get(cur.equipment_id) || []) {
        const child = byId.get(childId);
        if (child) queue.push(child);
      }
    }
    for (const e of eq) {
      if (!seen.has(e.equipment_id)) out.push(e);
    }
    return out;
  }, [graph]);

  async function deletePoint(id: string, label: string) {
    if (!window.confirm(`Remove point "${label}" from the model? BACnet poll will be disabled for this point.`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/model/points/${encodeURIComponent(id)}`, { method: "DELETE" });
      onStatus?.(`Deleted point ${label}`);
      await load();
      onModelChange?.();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
      setMenu(null);
    }
  }

  async function deleteEquipment(id: string, label: string) {
    if (!window.confirm(`Remove equipment "${label}" and its points from the model?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/model/equipment/${encodeURIComponent(id)}`, { method: "DELETE" });
      onStatus?.(`Deleted equipment ${label}`);
      await load();
      onModelChange?.();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
      setMenu(null);
    }
  }

  function openContextMenu(e: MouseEvent, target: ContextTarget) {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ ...target, x: e.clientX, y: e.clientY });
  }

  function deleteTargetKeyDown(e: KeyboardEvent, target: ContextTarget) {
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    e.preventDefault();
    if (target.kind === "point") void deletePoint(target.id, target.label);
    else void deleteEquipment(target.id, target.label);
  }

  function deletableProps(target: ContextTarget) {
    const kindLabel = target.kind === "point" ? "Point" : "Equipment";
    return {
      tabIndex: 0,
      role: "button" as const,
      "aria-label": `${kindLabel} ${target.label}. Press Delete to remove.`,
      onContextMenu: (e: MouseEvent) => openContextMenu(e, target),
      onKeyDown: (e: KeyboardEvent) => deleteTargetKeyDown(e, target),
    };
  }

  const pointsMap = graph?.points_by_equipment ?? {};

  return (
    <div className="dm-explorer dm-explorer-single">
      <section className="dm-graph-section panel dm-tree-panel">
        <h3 className="panel-title">BRICK model graph</h3>
        <p className="muted">
          Equipment, <code>brick:feeds</code> relationships, and points loaded via SPARQL
          {graph?.query_engine ? ` (${graph.query_engine})` : ""}. Map rules in{" "}
          <a href="/rule-lab">Rule Lab</a>.
        </p>

        {graph?.feeds?.length ? (
          <div className="dm-feeds-block">
            <h4>Feeds</h4>
            <ul className="dm-feeds-list">
              {graph.feeds.map((f) => (
                <li key={`${f.from_equipment_id}-${f.to_equipment_id}`}>
                  <span className="dm-feed-from">{f.from_label || f.from_equipment_id}</span>
                  <span className="dm-feed-arrow" aria-hidden="true">
                    → feeds →
                  </span>
                  <span className="dm-feed-to">{f.to_label || f.to_equipment_id}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted dm-feeds-empty">No feeds edges yet — sync TTL after AHU/VAV equipment exist.</p>
        )}

        {orderedEquipment.length ? (
          <div className="dm-tree">
            {orderedEquipment.map((eq) => {
              const pts = pointsMap[eq.equipment_id] ?? [];
              const inst = eq.bacnet_device_instance;
              const fedFrom = (graph?.feeds || []).filter((f) => f.to_equipment_id === eq.equipment_id);
              return (
                <div key={eq.equipment_id} className="dm-eq-block">
                  <div
                    className="dm-eq-head dm-focusable"
                    {...deletableProps({
                      kind: "equipment",
                      id: eq.equipment_id,
                      label: eqLabel(eq),
                    })}
                  >
                    <strong>{eqLabel(eq)}</strong>
                    {fedFrom.length ? (
                      <span className="badge dm-feed-badge">
                        fed by {fedFrom.map((f) => f.from_label || f.from_equipment_id).join(", ")}
                      </span>
                    ) : null}
                    {inst != null ? <span className="muted"> · device {inst}</span> : null}
                    {eq.equipment_type || eq.brick_type ? (
                      <span className="muted"> · {eq.equipment_type || eq.brick_type}</span>
                    ) : null}
                    <span className="dm-eq-count muted"> · {pts.length} pts</span>
                  </div>
                  <ul className="rule-map-points dm-tree-points">
                    {pts.map((p) => (
                      <li
                        key={p.point_id}
                        className="dm-point-row dm-focusable"
                        {...deletableProps({
                          kind: "point",
                          id: p.point_id,
                          label: pointLabel(p),
                        })}
                      >
                        <span className="dm-point-name">{pointLabel(p)}</span>
                        <span className="dm-point-meta">
                          {p.timeseries_column ? (
                            <code className="dm-point-addr">{p.timeseries_column}</code>
                          ) : null}
                          <span className="dm-point-sep" aria-hidden="true">
                            {" "}
                            ·{" "}
                          </span>
                          <span className="dm-point-brick">{p.brick_type || "—"}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="muted">No equipment rows. Enable BACnet polling or import a model.</p>
        )}
      </section>

      {menu ? (
        <div
          ref={menuRef}
          className="dm-context-menu"
          style={{ top: menu.y, left: menu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            className="dm-context-danger"
            onClick={() =>
              menu.kind === "point"
                ? void deletePoint(menu.id, menu.label)
                : void deleteEquipment(menu.id, menu.label)
            }
          >
            Delete {menu.kind === "point" ? "point" : "equipment"}…
          </button>
        </div>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
      {busy ? <p className="muted">Updating model…</p> : null}
    </div>
  );
}
