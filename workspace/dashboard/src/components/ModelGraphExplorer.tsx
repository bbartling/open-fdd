import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type ModelPoint = {
  id: string;
  site_id?: string;
  equipment_id?: string;
  external_id?: string;
  brick_type?: string;
  fdd_input?: string;
  description?: string;
  bacnet_device_id?: number | string;
  object_identifier?: string;
  metadata?: { point_id?: string; poll_interval_s?: string };
};

type ModelEquipment = {
  id: string;
  site_id?: string;
  name?: string;
  equipment_type?: string;
};

type SavedRule = {
  id: string;
  name: string;
  severity: string;
  enabled: boolean;
  bindings?: {
    point_ids?: string[];
    equipment_ids?: string[];
    brick_types?: string[];
  };
};

type ContextTarget =
  | { kind: "point"; id: string; label: string }
  | { kind: "equipment"; id: string; label: string };

type Props = {
  onStatus?: (msg: string) => void;
  refreshKey?: number;
  onModelChange?: () => void;
};

type DropKind = "point" | "equipment" | "brick_type";

export default function ModelGraphExplorer({ onStatus, refreshKey = 0, onModelChange }: Props) {
  const [rules, setRules] = useState<SavedRule[]>([]);
  const [equipment, setEquipment] = useState<ModelEquipment[]>([]);
  const [points, setPoints] = useState<ModelPoint[]>([]);
  const [brickTypes, setBrickTypes] = useState<string[]>([]);
  const [dragRuleId, setDragRuleId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expandedBrick, setExpandedBrick] = useState<Set<string>>(new Set());
  const [expandedEq, setExpandedEq] = useState<Set<string>>(new Set());
  const [menu, setMenu] = useState<(ContextTarget & { x: number; y: number }) | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const [tree, saved] = await Promise.all([
      apiFetch<{
        equipment: ModelEquipment[];
        points: ModelPoint[];
        brick_types: string[];
      }>("/api/model/tree"),
      apiFetch<{ rules: SavedRule[] }>("/api/rules/saved"),
    ]);
    setEquipment(tree.equipment ?? []);
    setPoints(tree.points ?? []);
    setBrickTypes(tree.brick_types ?? []);
    setRules(saved.rules ?? []);
    setExpandedBrick(new Set(tree.brick_types ?? []));
    setExpandedEq(new Set((tree.equipment ?? []).map((e) => e.id)));
  }, []);

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

  const eqById = useMemo(() => new Map(equipment.map((e) => [e.id, e])), [equipment]);

  const pointsByBrick = useMemo(() => {
    const map = new Map<string, ModelPoint[]>();
    for (const bt of brickTypes) map.set(bt, []);
    const unclassified: ModelPoint[] = [];
    for (const p of points) {
      const bt = str(p.brick_type);
      if (bt && map.has(bt)) map.get(bt)!.push(p);
      else if (bt) {
        if (!map.has(bt)) map.set(bt, []);
        map.get(bt)!.push(p);
      } else unclassified.push(p);
    }
    if (unclassified.length) map.set("(no BRICK class)", unclassified);
    return map;
  }, [points, brickTypes]);

  const eqGroups = useMemo(() => {
    const byEq = new Map<string, ModelPoint[]>();
    for (const p of points) {
      const eq = p.equipment_id || "unassigned";
      if (!byEq.has(eq)) byEq.set(eq, []);
      byEq.get(eq)!.push(p);
    }
    return byEq;
  }, [points]);

  function str(v: unknown): string {
    return String(v ?? "").trim();
  }

  function ruleBound(ruleId: string, kind: DropKind, targetId: string): boolean {
    const rule = rules.find((r) => r.id === ruleId);
    const b = rule?.bindings;
    if (!b) return false;
    if (kind === "point") return (b.point_ids ?? []).includes(targetId);
    if (kind === "equipment") return (b.equipment_ids ?? []).includes(targetId);
    return (b.brick_types ?? []).includes(targetId);
  }

  async function bindRule(ruleId: string, kind: DropKind, targetId: string) {
    const rule = rules.find((r) => r.id === ruleId);
    if (!rule) return;
    const prev = rule.bindings ?? { point_ids: [], equipment_ids: [], brick_types: [] };
    const next = {
      point_ids: [...(prev.point_ids ?? [])],
      equipment_ids: [...(prev.equipment_ids ?? [])],
      brick_types: [...(prev.brick_types ?? [])],
    };
    if (kind === "point" && !next.point_ids.includes(targetId)) next.point_ids.push(targetId);
    if (kind === "equipment" && !next.equipment_ids.includes(targetId)) next.equipment_ids.push(targetId);
    if (kind === "brick_type" && !next.brick_types.includes(targetId)) next.brick_types.push(targetId);

    setBusy(true);
    setError("");
    try {
      await apiFetch("/api/rules/bindings", {
        method: "POST",
        body: JSON.stringify({
          rule_id: ruleId,
          point_ids: next.point_ids,
          equipment_ids: next.equipment_ids,
          brick_types: next.brick_types,
        }),
      });
      onStatus?.(`Mapped "${rule.name}" → ${targetId}`);
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }

  function onDrop(e: React.DragEvent, kind: DropKind, targetId: string) {
    e.preventDefault();
    const ruleId = e.dataTransfer.getData("application/x-ofdd-rule") || dragRuleId;
    if (!ruleId) return;
    void bindRule(ruleId, kind, targetId);
  }

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

  async function runBatch() {
    setBusy(true);
    try {
      const res = await apiFetch<{ flagged_runs: number; error_runs: number }>("/api/rules/batch", {
        method: "POST",
        body: JSON.stringify({ limit: 1000 }),
      });
      onStatus?.(`Batch run — flagged=${res.flagged_runs} errors=${res.error_runs}`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function toggleBrick(bt: string) {
    setExpandedBrick((prev) => {
      const next = new Set(prev);
      if (next.has(bt)) next.delete(bt);
      else next.add(bt);
      return next;
    });
  }

  function toggleEq(id: string) {
    setExpandedEq((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openContextMenu(e: React.MouseEvent, target: ContextTarget) {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ ...target, x: e.clientX, y: e.clientY });
  }

  const brickEntries = [...pointsByBrick.entries()].filter(([, pts]) => pts.length > 0);

  return (
    <div className="dm-explorer">
      <aside className="dm-explorer-rules panel">
        <h3 className="panel-title">Fault rules</h3>
        <p className="muted">Drag onto a BRICK class, equipment, or point.</p>
        {rules.length ? (
          <ul className="rule-map-rules">
            {rules.map((r) => (
              <li
                key={r.id}
                draggable
                onDragStart={(e) => {
                  setDragRuleId(r.id);
                  e.dataTransfer.setData("application/x-ofdd-rule", r.id);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                onDragEnd={() => setDragRuleId(null)}
                className={dragRuleId === r.id ? "dragging" : ""}
              >
                <strong>{r.name}</strong>
                <span className="badge">{r.severity}</span>
                {(r.bindings?.point_ids?.length ?? 0) +
                  (r.bindings?.equipment_ids?.length ?? 0) +
                  (r.bindings?.brick_types?.length ?? 0) >
                0 ? (
                  <span className="badge poll-badge">mapped</span>
                ) : (
                  <span className="badge muted-badge">unmapped</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            No saved rules. <Link to="/rule-lab">Create one in Rule Lab</Link>.
          </p>
        )}
        <button type="button" className="secondary-btn" disabled={busy || !rules.length} onClick={() => void runBatch()}>
          Run batch now
        </button>
      </aside>

      <div className="dm-explorer-main">
        <section className="dm-graph-section panel">
          <h3 className="panel-title">By BRICK class</h3>
          <p className="muted">Each class groups sensors that share the same ontology type. Drop rules on a class header.</p>
          {brickEntries.length ? (
            <div className="dm-brick-grid">
              {brickEntries.map(([bt, pts]) => (
                <article key={bt} className="dm-brick-node">
                  <header
                    className="dm-brick-head rule-map-drop"
                    onDragOver={onDragOver}
                    onDrop={(e) => onDrop(e, "brick_type", bt === "(no BRICK class)" ? "" : bt)}
                  >
                    <button type="button" className="dm-expand-btn" onClick={() => toggleBrick(bt)} aria-expanded={expandedBrick.has(bt)}>
                      {expandedBrick.has(bt) ? "▾" : "▸"}
                    </button>
                    <code>{bt}</code>
                    <span className="badge">{pts.length}</span>
                    {rules
                      .filter((r) => bt !== "(no BRICK class)" && ruleBound(r.id, "brick_type", bt))
                      .map((r) => (
                        <span key={r.id} className="badge poll-badge">
                          {r.name}
                        </span>
                      ))}
                  </header>
                  {expandedBrick.has(bt) ? (
                    <ul className="dm-point-list">
                      {pts.map((p) => {
                        const eq = eqById.get(str(p.equipment_id));
                        const label = str(p.external_id) || str(p.fdd_input) || p.id;
                        return (
                          <li
                            key={p.id}
                            className="dm-point-chip rule-map-drop"
                            onDragOver={onDragOver}
                            onDrop={(e) => onDrop(e, "point", p.id)}
                            onContextMenu={(e) => openContextMenu(e, { kind: "point", id: p.id, label })}
                          >
                            <span className="dm-point-label">{label}</span>
                            <span className="muted">{eq?.name || p.description || "—"}</span>
                            {rules.filter((r) => ruleBound(r.id, "point", p.id)).map((r) => (
                              <span key={r.id} className="badge poll-badge">
                                {r.name}
                              </span>
                            ))}
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <p className="muted">No points yet. Enable BACnet polling or import a model.</p>
          )}
        </section>

        <section className="dm-graph-section panel">
          <h3 className="panel-title">By equipment</h3>
          <p className="muted">Right-click a point or equipment row to delete. BACnet rows stay aligned via Sync poll → model.</p>
          {equipment.length ? (
            equipment.map((eq) => (
              <div key={eq.id} className="dm-eq-block">
                <div
                  className="dm-eq-head rule-map-drop"
                  onDragOver={onDragOver}
                  onDrop={(e) => onDrop(e, "equipment", eq.id)}
                  onContextMenu={(e) => openContextMenu(e, { kind: "equipment", id: eq.id, label: eq.name || eq.id })}
                >
                  <button type="button" className="dm-expand-btn" onClick={() => toggleEq(eq.id)} aria-expanded={expandedEq.has(eq.id)}>
                    {expandedEq.has(eq.id) ? "▾" : "▸"}
                  </button>
                  <strong>{eq.name || eq.id}</strong>
                  {eq.equipment_type ? <span className="muted"> · {eq.equipment_type}</span> : null}
                  {rules.filter((r) => ruleBound(r.id, "equipment", eq.id)).map((r) => (
                    <span key={r.id} className="badge poll-badge">
                      {r.name}
                    </span>
                  ))}
                </div>
                {expandedEq.has(eq.id) ? (
                  <ul className="rule-map-points">
                    {(eqGroups.get(eq.id) ?? []).map((p) => (
                      <li
                        key={p.id}
                        className="rule-map-drop dm-point-row"
                        onDragOver={onDragOver}
                        onDrop={(e) => onDrop(e, "point", p.id)}
                        onContextMenu={(e) =>
                          openContextMenu(e, {
                            kind: "point",
                            id: p.id,
                            label: str(p.external_id) || p.id,
                          })
                        }
                      >
                        <code>{p.external_id || p.fdd_input || p.id}</code>
                        <span className="muted">{p.brick_type || p.description || "—"}</span>
                        {p.metadata?.poll_interval_s ? (
                          <span className="badge poll-badge">poll {p.metadata.poll_interval_s}s</span>
                        ) : null}
                        {rules.filter((r) => ruleBound(r.id, "point", p.id)).map((r) => (
                          <span key={r.id} className="badge poll-badge">
                            {r.name}
                          </span>
                        ))}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))
          ) : (
            <p className="muted">No equipment rows.</p>
          )}
        </section>
      </div>

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
    </div>
  );
}
