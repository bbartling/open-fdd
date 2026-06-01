import { useCallback, useEffect, useMemo, useState } from "react";
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

type Props = {
  onStatus?: (msg: string) => void;
};

type DropKind = "point" | "equipment" | "brick_type";

export default function RuleMappingBoard({ onStatus }: Props) {
  const [rules, setRules] = useState<SavedRule[]>([]);
  const [equipment, setEquipment] = useState<ModelEquipment[]>([]);
  const [points, setPoints] = useState<ModelPoint[]>([]);
  const [brickTypes, setBrickTypes] = useState<string[]>([]);
  const [dragRuleId, setDragRuleId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
  }, []);

  useEffect(() => {
    load().catch((e) => setError(formatApiError(e)));
  }, [load]);

  const ruleBindings = useMemo(() => {
    const map = new Map<string, SavedRule["bindings"]>();
    for (const r of rules) map.set(r.id, r.bindings ?? {});
    return map;
  }, [rules]);

  function ruleBound(ruleId: string, kind: DropKind, targetId: string): boolean {
    const b = ruleBindings.get(ruleId);
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

  const eqGroups = useMemo(() => {
    const byEq = new Map<string, ModelPoint[]>();
    for (const p of points) {
      const eq = p.equipment_id || "unassigned";
      if (!byEq.has(eq)) byEq.set(eq, []);
      byEq.get(eq)!.push(p);
    }
    return byEq;
  }, [points]);

  return (
    <div className="rule-map-board">
      <div className="rule-map-col">
        <h3 className="panel-title">Fault rules</h3>
        <p className="muted">Drag a rule onto equipment, a point, or a BRICK type.</p>
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
            No saved rules. Create one in <a href="/rule-lab">Rule Lab</a>.
          </p>
        )}
        <button type="button" className="secondary-btn" disabled={busy || !rules.length} onClick={() => void runBatch()}>
          Run batch now
        </button>
      </div>

      <div className="rule-map-col rule-map-targets">
        <h3 className="panel-title">BRICK model targets</h3>
        {brickTypes.length ? (
          <div className="rule-map-section">
            <h4>Sensor / point classes</h4>
            <div className="rule-map-drop-grid">
              {brickTypes.map((bt) => (
                <div
                  key={bt}
                  className="rule-map-drop"
                  onDragOver={onDragOver}
                  onDrop={(e) => onDrop(e, "brick_type", bt)}
                >
                  <code>{bt}</code>
                  {rules.filter((r) => ruleBound(r.id, "brick_type", bt)).map((r) => (
                    <span key={r.id} className="badge poll-badge">
                      {r.name}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="rule-map-section">
          <h4>Equipment &amp; points</h4>
          {equipment.length ? (
            equipment.map((eq) => (
              <div key={eq.id} className="rule-map-eq">
                <div
                  className="rule-map-eq-head rule-map-drop"
                  onDragOver={onDragOver}
                  onDrop={(e) => onDrop(e, "equipment", eq.id)}
                >
                  <strong>{eq.name || eq.id}</strong>
                  {eq.equipment_type ? <span className="muted"> · {eq.equipment_type}</span> : null}
                  {rules.filter((r) => ruleBound(r.id, "equipment", eq.id)).map((r) => (
                    <span key={r.id} className="badge poll-badge">
                      {r.name}
                    </span>
                  ))}
                </div>
                <ul className="rule-map-points">
                  {(eqGroups.get(eq.id) ?? []).map((p) => (
                    <li
                      key={p.id}
                      className="rule-map-drop"
                      onDragOver={onDragOver}
                      onDrop={(e) => onDrop(e, "point", p.id)}
                    >
                      <code>{p.external_id || p.fdd_input || p.id}</code>
                      <span className="muted">{p.description || p.brick_type}</span>
                      {rules.filter((r) => ruleBound(r.id, "point", p.id)).map((r) => (
                        <span key={r.id} className="badge poll-badge">
                          {r.name}
                        </span>
                      ))}
                    </li>
                  ))}
                </ul>
              </div>
            ))
          ) : (
            <p className="muted">Import a model or add BACnet points to populate targets.</p>
          )}
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
    </div>
  );
}
