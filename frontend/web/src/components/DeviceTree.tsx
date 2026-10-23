import { useMemo, type ReactNode } from "react";
import type { HistorianPoint } from "../api/historianApi";
import { groupDeviceTree, type DeviceTreeEquipment } from "../lib/deviceTree";

export interface DeviceTreeProps {
  points: readonly HistorianPoint[];
  testId?: string;
  /** Extra controls beside an equipment row. The tree itself is read-only. */
  equipmentActions?: (equipment: DeviceTreeEquipment) => ReactNode;
  pointActions?: (point: HistorianPoint) => ReactNode;
}

/** Read-only equipment → point view of the historian series for one site. */
export function DeviceTree({
  points,
  testId = "device-tree",
  equipmentActions,
  pointActions,
}: DeviceTreeProps) {
  const groups = useMemo(() => groupDeviceTree(points), [points]);
  if (groups.length === 0) {
    return (
      <p data-testid={`${testId}-empty`}>No historian series for this site yet.</p>
    );
  }
  return (
    <ul className="device-tree" data-testid={testId} aria-label="Equipment and points">
      {groups.map((group) => {
        const label = group.equipmentId || "(no equipment)";
        return (
          <li key={label} data-testid={`${testId}-equipment-${label}`}>
            <div className="device-tree__equipment">
              <strong>{label}</strong>
                {group.equipType ? (
                  <>
                    {" "}
                    · <code>{group.equipType}</code>
                  </>
                ) : null}{" "}
                · {group.points.length} point{group.points.length === 1 ? "" : "s"}
                {group.orphaned > 0 ? (
                  <span className="device-tree__orphaned">
                    {" "}
                    · {group.orphaned} orphaned
                  </span>
                ) : null}
                {equipmentActions ? (
                  <span className="device-tree__actions">{equipmentActions(group)}</span>
                ) : null}
            </div>
            <ul>
                {group.points.map((point) => (
                  <li
                    key={point.openfdd_key}
                    data-testid={`${testId}-point-${point.openfdd_key}`}
                  >
                    <code>{point.role ?? "—"}</code> · {point.openfdd_key}
                    {point.unit ? <> · {point.unit}</> : null}
                    {point.referenced ? null : (
                      <span className="device-tree__orphaned">
                        {" "}
                        · orphaned (no longer in the model)
                      </span>
                    )}
                    {pointActions ? (
                      <span className="device-tree__actions">{pointActions(point)}</span>
                    ) : null}
                  </li>
                ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}
