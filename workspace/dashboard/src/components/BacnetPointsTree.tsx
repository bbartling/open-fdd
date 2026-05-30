import { useMemo, useState } from "react";
import ContextMenu, { type ContextMenuItem } from "./ContextMenu";
import type { InventoryDevice, PointDiscoveryObjectRow } from "../lib/bacnet-discovery-parse";

export type LiveDevice = {
  device_instance: number;
  device_address?: string;
  objects: PointDiscoveryObjectRow[];
};

type TreePoint = {
  id: string;
  name: string;
  meta: string;
  commandable: boolean;
  objectType: string;
};

type TreeDevice = {
  instance: string;
  address: string;
  points: TreePoint[];
};

type ContextTarget =
  | { kind: "device"; instance: string; address: string; pointCount: number }
  | { kind: "point"; instance: string; point: TreePoint }
  | null;

type Props = {
  inventory: InventoryDevice[];
  liveDevices: LiveDevice[];
  onAddDeviceToModel?: (instance: number, address: string, objects: PointDiscoveryObjectRow[]) => void;
  onAddPointToModel?: (instance: number, address: string, point: TreePoint) => void;
  onDiscoverDevice?: (instance: number) => void;
  onCopy?: (text: string) => void;
};

function mergeDevices(inventory: InventoryDevice[], liveDevices: LiveDevice[]): TreeDevice[] {
  const map = new Map<string, TreeDevice>();

  for (const dev of inventory) {
    map.set(dev.device_instance, {
      instance: dev.device_instance,
      address: dev.device_address,
      points: dev.points.map((p) => {
        const [objectType] = (p.object_identifier || "").split(",", 1);
        return {
          id: p.object_identifier || p.point_id,
          name: p.object_name || p.description || p.object_identifier,
          meta: [p.present_value, p.units].filter(Boolean).join(" "),
          commandable: false,
          objectType: objectType || "object",
        };
      }),
    });
  }

  for (const live of liveDevices) {
    const key = String(live.device_instance);
    const entry = map.get(key) ?? { instance: key, address: live.device_address ?? "", points: [] };
    if (live.device_address) entry.address = live.device_address;
    for (const obj of live.objects) {
      const [objectType] = obj.object_identifier.split(",", 1);
      if (entry.points.some((p) => p.id === obj.object_identifier)) continue;
      entry.points.push({
        id: obj.object_identifier,
        name: obj.name,
        meta: obj.commandable ? "commandable" : "",
        commandable: obj.commandable,
        objectType: objectType || "object",
      });
    }
    map.set(key, entry);
  }

  return Array.from(map.values()).sort((a, b) => Number(a.instance) - Number(b.instance));
}

function groupPoints(points: TreePoint[]): Map<string, TreePoint[]> {
  const groups = new Map<string, TreePoint[]>();
  for (const p of points) {
    const key = p.objectType || "object";
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

export default function BacnetPointsTree({
  inventory,
  liveDevices,
  onAddDeviceToModel,
  onAddPointToModel,
  onDiscoverDevice,
  onCopy,
}: Props) {
  const devices = useMemo(() => mergeDevices(inventory, liveDevices), [inventory, liveDevices]);
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(() => new Set());
  const [menu, setMenu] = useState<{ x: number; y: number; target: ContextTarget } | null>(null);

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

  function menuItems(): ContextMenuItem[] {
    if (!menu?.target) return [];
    const t = menu.target;
    if (t.kind === "device") {
      const inst = Number(t.instance);
      const live = liveDevices.find((d) => d.device_instance === inst);
      return [
        {
          id: "discover",
          label: "Run point discovery",
          onClick: () => onDiscoverDevice?.(inst),
        },
        {
          id: "add-device",
          label: `Add ${t.pointCount} point(s) to data model`,
          disabled: t.pointCount === 0,
          onClick: () =>
            onAddDeviceToModel?.(inst, t.address, live?.objects ?? []),
        },
        {
          id: "copy-inst",
          label: "Copy device instance",
          onClick: () => onCopy?.(t.instance),
        },
      ];
    }
    return [
      {
        id: "add-point",
        label: "Add point to data model",
        onClick: () => {
          const dev = devices.find((d) => d.instance === t.instance);
          onAddPointToModel?.(Number(t.instance), dev?.address ?? "", t.point);
        },
      },
      {
        id: "copy-oid",
        label: "Copy object identifier",
        onClick: () => onCopy?.(t.point.id),
      },
    ];
  }

  if (!devices.length) {
    return (
      <div className="bacnet-tree-empty">
        <p className="muted">No devices yet.</p>
        <p className="muted">Run <strong>Who-Is</strong>, select devices, then point discovery to populate this tree.</p>
      </div>
    );
  }

  return (
    <div className="bacnet-tree">
      {devices.map((dev) => {
        const devOpen = expandedDevices.has(dev.instance);
        const typeGroups = groupPoints(dev.points);
        return (
          <div key={dev.instance} className="bacnet-tree-device">
            <button
              type="button"
              className="bacnet-tree-device-head"
              onClick={() => toggleDevice(dev.instance)}
              onContextMenu={(e) =>
                openMenu(e, {
                  kind: "device",
                  instance: dev.instance,
                  address: dev.address,
                  pointCount: dev.points.length,
                })
              }
            >
              <span className="bacnet-tree-chevron">{devOpen ? "▾" : "▸"}</span>
              <span className="bacnet-tree-device-icon" aria-hidden>
                📡
              </span>
              <span className="bacnet-tree-device-title">
                Device <strong>{dev.instance}</strong>
                {dev.address ? <span className="muted"> @ {dev.address}</span> : null}
              </span>
              <span className="badge">{dev.points.length} pts</span>
            </button>
            {devOpen ? (
              <div className="bacnet-tree-device-body">
                {[...typeGroups.entries()].map(([typeName, pts]) => {
                  const typeKey = `${dev.instance}:${typeName}`;
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
                              key={`${dev.instance}-${p.id}`}
                              onContextMenu={(e) =>
                                openMenu(e, { kind: "point", instance: dev.instance, point: p })
                              }
                            >
                              <code>{p.id}</code>
                              <span className="bacnet-tree-point-name">{p.name}</span>
                              {p.commandable ? <span className="badge commandable-badge">cmd</span> : null}
                              {p.meta ? <span className="muted">{p.meta}</span> : null}
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
