import { useMemo, useState } from "react";
import type { InventoryDevice, PointDiscoveryObjectRow } from "../lib/bacnet-discovery-parse";

type LiveDevice = {
  device_instance: number;
  device_address?: string;
  objects: PointDiscoveryObjectRow[];
};

type Props = {
  inventory: InventoryDevice[];
  liveDevices: LiveDevice[];
};

function mergeDevices(inventory: InventoryDevice[], liveDevices: LiveDevice[]) {
  const map = new Map<string, { instance: string; address: string; points: Array<{ id: string; name: string; meta: string }> }>();

  for (const dev of inventory) {
    map.set(dev.device_instance, {
      instance: dev.device_instance,
      address: dev.device_address,
      points: dev.points.map((p) => ({
        id: p.object_identifier || p.point_id,
        name: p.object_name || p.description || p.object_identifier,
        meta: [p.present_value, p.units].filter(Boolean).join(" "),
      })),
    });
  }

  for (const live of liveDevices) {
    const key = String(live.device_instance);
    const entry = map.get(key) ?? {
      instance: key,
      address: live.device_address ?? "",
      points: [],
    };
    if (live.device_address) entry.address = live.device_address;
    for (const obj of live.objects) {
      const id = obj.object_identifier;
      if (entry.points.some((p) => p.id === id)) continue;
      entry.points.push({
        id,
        name: obj.name,
        meta: obj.commandable ? "commandable" : "",
      });
    }
    map.set(key, entry);
  }

  return Array.from(map.values()).sort((a, b) => Number(a.instance) - Number(b.instance));
}

export default function BacnetPointsTree({ inventory, liveDevices }: Props) {
  const devices = useMemo(() => mergeDevices(inventory, liveDevices), [inventory, liveDevices]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  function toggle(instance: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(instance)) next.delete(instance);
      else next.add(instance);
      return next;
    });
  }

  if (!devices.length) {
    return <p className="muted">No devices in tree yet — run Who-Is, then point discovery or Discover → CSV.</p>;
  }

  return (
    <div className="bacnet-tree">
      {devices.map((dev) => {
        const open = expanded.has(dev.instance);
        return (
          <div key={dev.instance} className="bacnet-tree-device">
            <button type="button" className="bacnet-tree-device-head" onClick={() => toggle(dev.instance)}>
              <span className="bacnet-tree-chevron">{open ? "▾" : "▸"}</span>
              <span className="bacnet-tree-device-title">
                Device {dev.instance}
                {dev.address ? <span className="muted"> @ {dev.address}</span> : null}
              </span>
              <span className="badge">{dev.points.length} pts</span>
            </button>
            {open ? (
              <ul className="bacnet-tree-points">
                {dev.points.map((p) => (
                  <li key={`${dev.instance}-${p.id}`}>
                    <code>{p.id}</code>
                    <span>{p.name}</span>
                    {p.meta ? <span className="muted">{p.meta}</span> : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
