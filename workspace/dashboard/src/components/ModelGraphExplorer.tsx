import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type ModelPoint = {
  id: string;
  site_id?: string;
  equipment_id?: string;
  external_id?: string;
  brick_type?: string;
  fdd_input?: string;
  name?: string;
  description?: string;
  bacnet_object?: string;
  metadata?: { poll_interval_s?: string };
};

type ModelEquipment = {
  id: string;
  site_id?: string;
  name?: string;
  equipment_type?: string;
  bacnet_device_instance?: number;
};

type ContextTarget =
  | { kind: "point"; id: string; label: string }
  | { kind: "equipment"; id: string; label: string };

type Props = {
  onStatus?: (msg: string) => void;
  refreshKey?: number;
  onModelChange?: () => void;
};

function pointAddress(p: ModelPoint): string {
  const ext = String(p.external_id || "").trim();
  if (ext) return ext;
  const fdd = String(p.fdd_input || "").trim();
  if (fdd) return fdd;
  return String(p.id || "").trim();
}

function pointDisplayName(p: ModelPoint): string {
  return String(p.name || p.description || pointAddress(p) || p.id);
}

export default function ModelGraphExplorer({ onStatus, refreshKey = 0, onModelChange }: Props) {
  const [equipment, setEquipment] = useState<ModelEquipment[]>([]);
  const [points, setPoints] = useState<ModelPoint[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState<(ContextTarget & { x: number; y: number }) | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const tree = await apiFetch<{
      equipment: ModelEquipment[];
      points: ModelPoint[];
    }>("/api/model/tree");
    setEquipment(tree.equipment ?? []);
    setPoints(tree.points ?? []);
    setError("");
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

  const eqGroups = useMemo(() => {
    const byEq = new Map<string, ModelPoint[]>();
    for (const p of points) {
      const eq = p.equipment_id || "unassigned";
      if (!byEq.has(eq)) byEq.set(eq, []);
      byEq.get(eq)!.push(p);
    }
    for (const [, list] of byEq) {
      list.sort((a, b) => pointDisplayName(a).localeCompare(pointDisplayName(b)));
    }
    return byEq;
  }, [points]);

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

  return (
    <div className="dm-explorer dm-explorer-single">
      <section className="dm-graph-section panel dm-tree-panel">
        <h3 className="panel-title">By equipment</h3>
        <p className="muted">
          Full equipment tree (always expanded). Map fault rules to BRICK classes in{" "}
          <a href="/rule-lab">Rule Lab</a>. Right-click or focus and press Delete to remove a row.
        </p>
        {equipment.length ? (
          <div className="dm-tree">
            {equipment.map((eq) => {
              const pts = eqGroups.get(eq.id) ?? [];
              const inst = eq.bacnet_device_instance;
              return (
                <div key={eq.id} className="dm-eq-block">
                  <div
                    className="dm-eq-head dm-focusable"
                    {...deletableProps({ kind: "equipment", id: eq.id, label: eq.name || eq.id })}
                  >
                    <strong>{eq.name || eq.id}</strong>
                    {inst != null ? <span className="muted"> · device {inst}</span> : null}
                    {eq.equipment_type ? <span className="muted"> · {eq.equipment_type}</span> : null}
                    <span className="dm-eq-count muted"> · {pts.length} pts</span>
                  </div>
                  <ul className="rule-map-points dm-tree-points">
                    {pts.map((p) => (
                      <li
                        key={p.id}
                        className="dm-point-row dm-focusable"
                        {...deletableProps({
                          kind: "point",
                          id: p.id,
                          label: pointDisplayName(p),
                        })}
                      >
                        <span className="dm-point-name">{pointDisplayName(p)}</span>
                        <span className="dm-point-meta">
                          <code className="dm-point-addr">{pointAddress(p)}</code>
                          <span className="dm-point-sep" aria-hidden="true">
                            {" "}
                            ·{" "}
                          </span>
                          <span className="dm-point-brick">{p.brick_type || "—"}</span>
                          {p.metadata?.poll_interval_s ? (
                            <span className="badge poll-badge">poll {p.metadata.poll_interval_s}s</span>
                          ) : null}
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
