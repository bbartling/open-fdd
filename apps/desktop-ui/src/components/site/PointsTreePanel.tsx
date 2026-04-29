import { useMemo } from "react";

type ModelPoint = {
  id?: string;
  site_id?: string;
  equipment_id?: string | null;
  external_id?: string;
  brick_type?: string | null;
  metadata?: Record<string, unknown> | null;
};

type ModelEquipment = {
  id?: string;
  site_id?: string;
  name?: string;
  equipment_type?: string | null;
};

type Group = {
  id: string;
  name: string;
  equipment_type?: string | null;
  points: ModelPoint[];
};

export function PointsTreePanel({
  points,
  equipment,
  selectedSiteId,
  selectedExternalIds,
  onSelectedExternalIdsChange,
  title = "Points tree",
  description,
  pointFilter,
}: {
  points: ModelPoint[];
  equipment: ModelEquipment[];
  selectedSiteId: string;
  selectedExternalIds: string[];
  onSelectedExternalIdsChange: (ids: string[]) => void;
  title?: string;
  description?: string;
  pointFilter?: (point: ModelPoint) => boolean;
}) {
  const groups = useMemo(() => {
    const isUsableExternalId = (value: unknown) => String(value ?? "").trim().length > 0;
    const byEquip = new Map<string, Group>();
    const out: Group[] = [];
    const equipById = new Map<string, ModelEquipment>();
    for (const eq of equipment) {
      if (String(eq.site_id || "") !== String(selectedSiteId || "")) continue;
      const id = String(eq.id || "");
      if (!id) continue;
      equipById.set(id, eq);
      const grp: Group = {
        id,
        name: String(eq.name || "Equipment"),
        equipment_type: eq.equipment_type ?? null,
        points: [],
      };
      byEquip.set(id, grp);
      out.push(grp);
    }

    const unassigned: Group = {
      id: "__unassigned__",
      name: "Unassigned",
      equipment_type: null,
      points: [],
    };

    for (const point of points) {
      if (!isUsableExternalId(point.external_id)) continue;
      if (String(point.site_id || "") !== String(selectedSiteId || "")) continue;
      if (pointFilter && !pointFilter(point)) continue;
      const eqId = String(point.equipment_id || "");
      if (!eqId || !equipById.has(eqId)) {
        unassigned.points.push(point);
        continue;
      }
      byEquip.get(eqId)?.points.push(point);
    }

    const withPoints = out.filter((g) => g.points.length > 0);
    if (unassigned.points.length > 0) withPoints.push(unassigned);
    return withPoints;
  }, [equipment, points, selectedSiteId, pointFilter]);

  function toggleExternalId(externalId: string, checked: boolean) {
    const next = new Set(selectedExternalIds);
    if (checked) next.add(externalId);
    else next.delete(externalId);
    onSelectedExternalIdsChange(Array.from(next));
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}>
      <h3 style={{ marginTop: 0, marginBottom: 6 }}>{title}</h3>
      {description ? <p className="muted" style={{ marginTop: 0 }}>{description}</p> : null}
      {groups.length === 0 ? (
        <div className="muted">No points available for this site.</div>
      ) : (
        <div style={{ maxHeight: 320, overflowY: "auto", display: "grid", gap: 6 }}>
          {groups.map((group) => (
            <details key={group.id} open>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                {group.name}
                {group.equipment_type ? ` (${group.equipment_type})` : ""}
                <span className="muted" style={{ marginLeft: 8 }}>({group.points.length})</span>
              </summary>
              <div style={{ marginTop: 6, marginLeft: 14, display: "grid", gap: 4 }}>
                {group.points.map((point) => {
                  const externalId = String(point.external_id || "").trim();
                  if (!externalId) return null;
                  const checked = selectedExternalIds.includes(externalId);
                  return (
                    <label key={`${group.id}-${externalId}`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        style={{ width: "auto" }}
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => toggleExternalId(externalId, e.target.checked)}
                      />
                      <span>{externalId}</span>
                      {point.brick_type ? <span className="muted">{String(point.brick_type)}</span> : null}
                    </label>
                  );
                })}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
