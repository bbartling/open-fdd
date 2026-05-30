import { useMemo, useState } from "react";
import ContextMenu, { type ContextMenuItem } from "./ContextMenu";

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
};

export type DriverDevice = {
  device_instance: string;
  device_address: string;
  point_count: number;
  poll_count: number;
  points: DriverPoint[];
};

const POLL_OPTIONS = [
  { seconds: 60, label: "1 min" },
  { seconds: 300, label: "5 min" },
  { seconds: 600, label: "10 min" },
  { seconds: 900, label: "15 min" },
] as const;

type ContextTarget =
  | { kind: "device"; device: DriverDevice }
  | { kind: "point"; device: DriverDevice; point: DriverPoint }
  | null;

type Props = {
  devices: DriverDevice[];
  onRefreshDevice?: (instance: number) => void;
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

export default function BacnetPointsTree({
  devices,
  onRefreshDevice,
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

  function pollItemsForPoint(point: DriverPoint): ContextMenuItem[] {
    const items: ContextMenuItem[] = POLL_OPTIONS.map((opt) => ({
      id: `poll-${opt.seconds}`,
      label: `Poll every ${opt.label}`,
      onClick: () => onSetPointPoll?.(point.point_id, true, opt.seconds),
    }));
    if (point.enabled) {
      items.push({
        id: "poll-off",
        label: "Stop polling",
        onClick: () => onSetPointPoll?.(point.point_id, false, 0),
      });
    }
    return items;
  }

  function menuItems(): ContextMenuItem[] {
    if (!menu?.target) return [];
    const t = menu.target;
    if (t.kind === "device") {
      const inst = Number(t.device.device_instance);
      const pollItems: ContextMenuItem[] = POLL_OPTIONS.map((opt) => ({
        id: `dev-poll-${opt.seconds}`,
        label: `Poll all — ${opt.label}`,
        disabled: t.device.point_count === 0,
        onClick: () => onSetDevicePoll?.(inst, true, opt.seconds),
      }));
      return [
        {
          id: "refresh",
          label: "Refresh points from device",
          onClick: () => onRefreshDevice?.(inst),
        },
        {
          id: "remap",
          label: "Edit instance / address…",
          onClick: () => onRemapDevice?.(t.device),
        },
        ...pollItems,
        {
          id: "poll-off-all",
          label: "Stop polling (all points)",
          disabled: t.device.poll_count === 0,
          onClick: () => onSetDevicePoll?.(inst, false, 0),
        },
        {
          id: "copy-inst",
          label: "Copy device instance",
          onClick: () => onCopy?.(t.device.device_instance),
        },
        {
          id: "delete-dev",
          label: "Remove device",
          danger: true,
          onClick: () => onDeleteDevice?.(inst),
        },
      ];
    }
    return [
      ...pollItemsForPoint(t.point),
      {
        id: "copy-oid",
        label: "Copy object id",
        onClick: () => onCopy?.(t.point.object_identifier),
      },
      {
        id: "delete-pt",
        label: "Remove point",
        danger: true,
        onClick: () => onDeletePoint?.(t.point.point_id),
      },
    ];
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
                          {pts.map((p) => (
                            <li
                              key={p.point_id}
                              onContextMenu={(e) => openMenu(e, { kind: "point", device: dev, point: p })}
                            >
                              <code>{p.object_identifier}</code>
                              <span className="bacnet-tree-point-name">{p.object_name}</span>
                              {p.enabled && p.present_value ? (
                                <span className="badge pv-badge" title="Last present value">
                                  {p.present_value}
                                </span>
                              ) : null}
                              {p.enabled ? (
                                <span className="badge poll-badge" title="Polling enabled">
                                  ⏱ {p.poll_label || `${p.poll_interval_s}s`}
                                </span>
                              ) : (
                                <span className="badge muted-badge">idle</span>
                              )}
                            </li>
                          ))}
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
