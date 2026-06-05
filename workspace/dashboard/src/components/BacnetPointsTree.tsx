import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import {
  buildDeviceContextMenuItems,
  buildPointContextMenuItems,
  formatBacnetValue,
  type PrioritySlot,
} from "../lib/bacnetTreeMenu";

export type OverrideSlot = {
  priority_level: number;
  type?: string;
  value?: unknown;
};

export type DriverPoint = {
  point_id: string;
  object_identifier: string;
  object_name: string;
  object_type: string;
  enabled: boolean;
  poll_interval_s: number;
  poll_label: string;
  present_value?: string;
  series_id?: string;
  commandable?: boolean;
  has_override?: boolean;
  override_priorities?: number[];
  operator_override?: boolean;
  operator_override_value?: string;
  override_slots?: OverrideSlot[];
};

export type DriverDevice = {
  device_instance: string;
  device_address: string;
  point_count: number;
  poll_count: number;
  override_point_count?: number;
  operator_override_count?: number;
  last_override_scan_at?: string;
  points: DriverPoint[];
};

type ContextTarget =
  | { kind: "device"; device: DriverDevice }
  | { kind: "point"; device: DriverDevice; point: DriverPoint }
  | null;

type Props = {
  devices: DriverDevice[];
  priorityByPointId?: Record<string, PrioritySlot[]>;
  expandedPriorityPoints?: Set<string>;
  onRefreshDevice?: (instance: number) => void;
  onRefreshPointPv?: (device: DriverDevice, point: DriverPoint) => void;
  onReadPriorityArray?: (device: DriverDevice, point: DriverPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onSetDevicePoll?: (instance: number, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
  onDeleteDevice?: (instance: number) => void;
  onRemapDevice?: (device: DriverDevice) => void;
  onCopy?: (text: string) => void;
};

function groupPoints(points: DriverPoint[]): Map<string, DriverPoint[]> {
  const groups = new Map<string, DriverPoint[]>();
  for (const p of points) {
    const key = p.object_type || "object";
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

function prioritySlotLabel(slot: PrioritySlot): string {
  if (slot.type === "null" || slot.value == null) return "null (relinquished)";
  return `${slot.type}: ${formatBacnetValue(slot.value)}`;
}

function overrideSlotLabel(slot: OverrideSlot): string {
  const val = slot.value;
  if (val == null || slot.type === "null") return "active";
  return `${slot.type ?? "value"}: ${formatBacnetValue(val)}`;
}

export default function BacnetPointsTree({
  devices,
  priorityByPointId = {},
  expandedPriorityPoints = new Set(),
  onRefreshDevice,
  onRefreshPointPv,
  onReadPriorityArray,
  onSetPointPoll,
  onSetDevicePoll,
  onDeletePoint,
  onDeleteDevice,
  onRemapDevice,
  onCopy,
}: Props) {
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(() => new Set());
  const [menu, setMenu] = useState<{ x: number; y: number; target: ContextTarget } | null>(null);

  const sorted = useMemo(
    () => [...devices].sort((a, b) => Number(a.device_instance) - Number(b.device_instance)),
    [devices],
  );

  function toggleDevice(instance: string) {
    setExpandedDevices((prev) => {
      const next = new Set(prev);
      if (next.has(instance)) next.delete(instance);
      else next.add(instance);
      return next;
    });
  }

  function toggleType(key: string) {
    setExpandedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function openMenu(e: React.MouseEvent, target: ContextTarget) {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, target });
  }

  function menuItems() {
    if (!menu?.target) return [];
    const t = menu.target;
    if (t.kind === "device") {
      return buildDeviceContextMenuItems({
        device: t.device,
        onRefreshDevice,
        onRemapDevice,
        onSetDevicePoll,
        onDeleteDevice,
        onCopy,
      });
    }
    return buildPointContextMenuItems({
      device: t.device,
      point: t.point,
      onRefreshPointPv,
      onReadPriorityArray,
      onSetPointPoll,
      onDeletePoint,
      onCopy,
    });
  }

  if (!sorted.length) {
    return (
      <div className="bacnet-tree-empty">
        <p className="muted">No devices added yet.</p>
        <p className="muted">Run Who-Is, select devices, then click <strong>Add device</strong>.</p>
      </div>
    );
  }

  return (
    <div className="bacnet-tree">
      {sorted.map((dev) => {
        const devOpen = expandedDevices.has(dev.device_instance);
        const typeGroups = groupPoints(dev.points);
        return (
          <div key={dev.device_instance} className="bacnet-tree-device">
            <button
              type="button"
              className="bacnet-tree-device-head"
              onClick={() => toggleDevice(dev.device_instance)}
              onContextMenu={(e) => openMenu(e, { kind: "device", device: dev })}
            >
              <span className="bacnet-tree-chevron">{devOpen ? "▾" : "▸"}</span>
              <span className="bacnet-tree-device-icon" aria-hidden>
                📡
              </span>
              <span className="bacnet-tree-device-title">
                Device <strong>{dev.device_instance}</strong>
                {dev.device_address ? <span className="muted"> @ {dev.device_address}</span> : null}
              </span>
              <span className="badge">{dev.point_count} pts</span>
              {dev.poll_count > 0 ? (
                <span className="badge poll-badge">{dev.poll_count} polling</span>
              ) : null}
              {(dev.override_point_count ?? 0) > 0 ? (
                <span className="badge override-badge" title="Priority-array overrides detected">
                  ⚠ {dev.override_point_count} ovrd
                </span>
              ) : null}
              {(dev.operator_override_count ?? 0) > 0 ? (
                <span className="badge operator-override-badge" title="Operator priority (P8) overrides">
                  P8×{dev.operator_override_count}
                </span>
              ) : null}
            </button>
            {devOpen ? (
              <div className="bacnet-tree-device-body">
                {[...typeGroups.entries()].map(([typeName, pts]) => {
                  const typeKey = `${dev.device_instance}:${typeName}`;
                  const typeOpen = expandedTypes.has(typeKey);
                  return (
                    <div key={typeKey} className="bacnet-tree-type">
                      <button type="button" className="bacnet-tree-type-head" onClick={() => toggleType(typeKey)}>
                        <span className="bacnet-tree-chevron">{typeOpen ? "▾" : "▸"}</span>
                        <span className="bacnet-tree-type-label">{typeName}</span>
                        <span className="badge">{pts.length}</span>
                      </button>
                      {typeOpen ? (
                        <ul className="bacnet-tree-points">
                          {pts.map((p) => {
                            const priorityOpen = expandedPriorityPoints.has(p.point_id);
                            const prioritySlots = priorityByPointId[p.point_id] ?? [];
                            const scanSlots = (p.override_slots ?? []) as OverrideSlot[];
                            const showOverrideTree = scanSlots.length > 0;
                            const showPv =
                              p.enabled && String(p.present_value ?? "") !== "";
                            return (
                              <li key={p.point_id}>
                                <div
                                  className="bacnet-tree-point-row"
                                  onContextMenu={(e) => openMenu(e, { kind: "point", device: dev, point: p })}
                                >
                                  <code>{p.object_identifier}</code>
                                  <span className="bacnet-tree-point-name">{p.object_name}</span>
                                  {p.commandable ? (
                                    <span className="badge commandable-badge" title="Commandable (priority-array)">
                                      cmd
                                    </span>
                                  ) : null}
                                  {p.has_override ? (
                                    <span
                                      className={`badge override-badge${p.operator_override ? " operator-override-badge" : ""}`}
                                      title={
                                        p.override_priorities?.length
                                          ? `Overrides at P${p.override_priorities.join(", P")}`
                                          : "Priority override active"
                                      }
                                    >
                                      ovrd P{p.override_priorities?.join("/P") ?? "?"}
                                    </span>
                                  ) : null}
                                  {showPv ? (
                                    <span className="badge pv-badge" title="Present value">
                                      {p.present_value}
                                    </span>
                                  ) : p.enabled ? (
                                    <span className="badge muted-badge" title="Polling — no successful read yet">
                                      no sample
                                    </span>
                                  ) : null}
                                  {p.enabled ? (
                                    <span className="badge poll-badge" title="Polling enabled">
                                      ⏱ {p.poll_label || `${p.poll_interval_s}s`}
                                    </span>
                                  ) : (
                                    <span className="badge muted-badge">idle</span>
                                  )}
                                </div>
                                {showOverrideTree ? (
                                  <ul className="bacnet-tree-priority bacnet-tree-override-scan">
                                    {scanSlots.map((slot) => (
                                      <li key={`${p.point_id}-scan-p${slot.priority_level}`}>
                                        <span className="bacnet-tree-priority-level">P{slot.priority_level}</span>
                                        <span className="bacnet-tree-priority-value">{overrideSlotLabel(slot)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : null}
                                {priorityOpen && prioritySlots.length ? (
                                  <ul className="bacnet-tree-priority">
                                    {prioritySlots.map((slot) => (
                                      <li key={`${p.point_id}-p${slot.priority_level}`}>
                                        <span className="bacnet-tree-priority-level">P{slot.priority_level}</span>
                                        <span className="bacnet-tree-priority-value">{prioritySlotLabel(slot)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : null}
                              </li>
                            );
                          })}
                        </ul>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
      {menu ? <ContextMenu x={menu.x} y={menu.y} items={menuItems()} onClose={() => setMenu(null)} /> : null}
    </div>
  );
}
