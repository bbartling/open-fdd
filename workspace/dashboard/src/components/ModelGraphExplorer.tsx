import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  bindRuleToEquipmentPoints,
  bindRuleToTarget,
  fetchSavedRules,
  rulesBoundToTarget,
  unbindAllRulesFromTarget,
  unbindRuleFromTarget,
  type BindTarget,
  type SavedRule,
} from "../lib/ruleBindings";
import { formatRuleLabel } from "../lib/ruleDisplay";

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
  | { kind: "point"; id: string; label: string; equipmentId: string; brickType?: string }
  | {
      kind: "equipment";
      id: string;
      label: string;
      pointIds: string[];
      brickTypes: string[];
    };

type MenuView = "main" | "apply-brick";

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

function bindTargetFromContext(target: ContextTarget): BindTarget {
  if (target.kind === "point") {
    return { kind: "point", id: target.id, label: target.label };
  }
  return {
    kind: "equipment",
    id: target.id,
    label: target.label,
    pointIds: target.pointIds,
  };
}

export default function ModelGraphExplorer({ siteId, onStatus, refreshKey = 0, onModelChange }: Props) {
  const [graph, setGraph] = useState<ModelGraph | null>(null);
  const [rules, setRules] = useState<SavedRule[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState<(ContextTarget & { x: number; y: number; view: MenuView; brickType?: string }) | null>(
    null,
  );
  const menuRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const q = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
    const [data, saved] = await Promise.all([
      apiFetch<ModelGraph>(`/api/model/graph${q}`),
      fetchSavedRules(),
    ]);
    setGraph(data);
    setRules(saved);
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

  const rulesById = useMemo(() => new Map(rules.map((r) => [r.id, r])), [rules]);

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
    const roots = eq.filter(
      (e) => !(graph.feeds || []).some((f) => f.to_equipment_id === e.equipment_id),
    );
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

  function rulesOnPoint(pointId: string): SavedRule[] {
    return rulesBoundToTarget(rules, { kind: "point", id: pointId, label: pointId });
  }

  async function applyRule(
    ruleId: string,
    mode: "point" | "equipment" | "equipment-points" | "brick",
    target: ContextTarget,
    brickType?: string,
  ) {
    const rule = rulesById.get(ruleId);
    if (!rule) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "point" && target.kind === "point") {
        await bindRuleToTarget(rule, "point", target.id);
        onStatus?.(`Applied "${rule.name}" → point ${target.label}`);
      } else if (mode === "equipment" && target.kind === "equipment") {
        await bindRuleToTarget(rule, "equipment", target.id);
        onStatus?.(`Applied "${rule.name}" → equipment ${target.label}`);
      } else if (mode === "equipment-points" && target.kind === "equipment") {
        await bindRuleToEquipmentPoints(rule, target.id, target.pointIds);
        onStatus?.(`Applied "${rule.name}" → ${target.pointIds.length} points on ${target.label}`);
      } else if (mode === "brick" && target.kind === "equipment" && brickType) {
        const matchIds = (graph?.points_by_equipment[target.id] ?? [])
          .filter((p) => (p.brick_type || "") === brickType)
          .map((p) => p.point_id);
        await bindRuleToTarget(rule, "brick_type", brickType, matchIds);
        onStatus?.(`Applied "${rule.name}" → ${brickType} (${matchIds.length} pts)`);
      }
      await load();
      onModelChange?.();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
      setMenu(null);
    }
  }

  async function removeAllFdd(target: ContextTarget) {
    const bindTarget =
      target.kind === "point"
        ? { kind: "point" as const, id: target.id, label: target.label }
        : {
            kind: "equipment" as const,
            id: target.id,
            label: target.label,
            pointIds: target.pointIds,
          };
    setBusy(true);
    try {
      await unbindAllRulesFromTarget(rules, bindTarget);
      if (target.kind === "equipment") {
        for (const bt of target.brickTypes) {
          const matchIds = (graph?.points_by_equipment[target.id] ?? [])
            .filter((p) => (p.brick_type || "") === bt)
            .map((p) => p.point_id);
          await unbindAllRulesFromTarget(rules, {
            kind: "brick_type",
            id: bt,
            label: bt,
            pointIds: matchIds,
          });
        }
      }
      onStatus?.(`Removed FDD mappings from ${target.label}`);
      await load();
      onModelChange?.();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
      setMenu(null);
    }
  }

  async function removeOneRule(ruleId: string, target: ContextTarget) {
    const rule = rulesById.get(ruleId);
    if (!rule) return;
    setBusy(true);
    try {
      await unbindRuleFromTarget(rule, bindTargetFromContext(target));
      onStatus?.(`Removed "${rule.name}" from ${target.label}`);
      await load();
      onModelChange?.();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
      setMenu(null);
    }
  }

  async function deletePoint(id: string, label: string) {
    if (!window.confirm(`Remove point "${label}" from the model? BACnet poll will be disabled for this point.`))
      return;
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
    setMenu({ ...target, x: e.clientX, y: e.clientY, view: "main" });
  }

  function rowProps(target: ContextTarget) {
    return {
      tabIndex: 0,
      role: "button" as const,
      onContextMenu: (e: MouseEvent) => openContextMenu(e, target),
    };
  }

  function renderContextMenu() {
    if (!menu) return null;
    const bound = rulesBoundToTarget(rules, bindTargetFromContext(menu));
    const enabledRules = rules.filter((r) => r.enabled !== false);

    if (menu.view === "apply-brick" && menu.kind === "equipment") {
      return (
        <>
          <button type="button" className="dm-context-back" onClick={() => setMenu({ ...menu, view: "main" })}>
            ← Back
          </button>
          <p className="dm-context-hint">Pick a sensor class on {menu.label}</p>
          {menu.brickTypes.map((bt) => (
            <button key={bt} type="button" onClick={() => setMenu({ ...menu, view: "main", brickType: bt })}>
              {bt} (
              {(graph?.points_by_equipment[menu.id] ?? []).filter((p) => p.brick_type === bt).length} pts)
            </button>
          ))}
        </>
      );
    }

    const brickType = menu.brickType;
    const showBrickRuleList = brickType && menu.kind === "equipment";

    return (
      <>
        <p className="dm-context-hint">FDD rules — {menu.label}</p>
        {!enabledRules.length ? (
          <p className="dm-context-muted">No enabled rules. Create one in Rule Lab.</p>
        ) : null}
        {showBrickRuleList
          ? enabledRules.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => void applyRule(r.id, "brick", menu, brickType)}
              >
                Apply: {formatRuleLabel(r.name)}
              </button>
            ))
          : null}
        {!showBrickRuleList && menu.kind === "point"
          ? enabledRules.map((r) => (
              <button key={r.id} type="button" onClick={() => void applyRule(r.id, "point", menu)}>
                Apply: {formatRuleLabel(r.name)}
              </button>
            ))
          : null}
        {!showBrickRuleList && menu.kind === "equipment"
          ? enabledRules.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => void applyRule(r.id, "equipment", menu)}
              >
                Apply to device: {formatRuleLabel(r.name)}
              </button>
            ))
          : null}
        {!showBrickRuleList && menu.kind === "equipment"
          ? enabledRules.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => void applyRule(r.id, "equipment-points", menu)}
              >
                Apply to all points: {formatRuleLabel(r.name)}
              </button>
            ))
          : null}
        {!showBrickRuleList && menu.kind === "equipment" && menu.brickTypes.length > 0 ? (
          <button type="button" onClick={() => setMenu({ ...menu, view: "apply-brick" })}>
            Apply by BRICK class…
          </button>
        ) : null}
        {bound.length > 0 ? (
          <>
            <div className="dm-context-sep" />
            <p className="dm-context-hint">Remove mapping</p>
            {bound.map((r) => (
              <button key={`rm-${r.id}`} type="button" onClick={() => void removeOneRule(r.id, menu)}>
                Remove: {formatRuleLabel(r.name)}
              </button>
            ))}
            <button type="button" onClick={() => void removeAllFdd(menu)}>
              Remove all FDD from {menu.kind === "point" ? "point" : "equipment"}
            </button>
          </>
        ) : null}
        <div className="dm-context-sep" />
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
      </>
    );
  }

  const pointsMap = graph?.points_by_equipment ?? {};

  return (
    <div className="dm-explorer dm-explorer-single">
      <section className="dm-graph-section panel dm-tree-panel">
        <h3 className="panel-title">BRICK model graph</h3>
        <p className="muted">
          Right-click a point or equipment for FDD rule mapping. Assignments are summarized in{" "}
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
              const brickTypes = [...new Set(pts.map((p) => p.brick_type).filter(Boolean) as string[])].sort();
              const eqTarget: ContextTarget = {
                kind: "equipment",
                id: eq.equipment_id,
                label: eqLabel(eq),
                pointIds: pts.map((p) => p.point_id),
                brickTypes,
              };
              return (
                <div key={eq.equipment_id} className="dm-eq-block">
                  <div className="dm-eq-head dm-focusable" {...rowProps(eqTarget)}>
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
                    {pts.map((p) => {
                      const bound = rulesOnPoint(p.point_id);
                      return (
                        <li
                          key={p.point_id}
                          className="dm-point-row dm-focusable"
                          {...rowProps({
                            kind: "point",
                            id: p.point_id,
                            label: pointLabel(p),
                            equipmentId: eq.equipment_id,
                            brickType: p.brick_type,
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
                          {bound.length ? (
                            <span className="dm-point-rules">
                              {bound.map((r) => (
                                <span key={r.id} className="badge poll-badge" title={r.name}>
                                  {formatRuleLabel(r.name)}
                                </span>
                              ))}
                            </span>
                          ) : null}
                        </li>
                      );
                    })}
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
          className="dm-context-menu dm-context-menu-wide"
          style={{ top: menu.y, left: menu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          {renderContextMenu()}
        </div>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
      {busy ? <p className="muted">Updating model…</p> : null}
    </div>
  );
}
