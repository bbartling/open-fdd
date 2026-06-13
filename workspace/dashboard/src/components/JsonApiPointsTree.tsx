import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import { buildDeviceContextMenuItems, buildPointContextMenuItems } from "../lib/jsonApiTreeMenu";

export type JsonApiPoint = {
  point_id: string;
  label: string;
  url: string;
  method: string;
  json_path: string;
  object_type?: string;
  object_identifier?: string;
  object_name?: string;
  enabled: boolean;
  poll_interval_s: number;
  poll_label: string;
  present_value?: string;
  units?: string;
  last_read_at?: string;
};

export type JsonApiDevice = {
  device_key: string;
  host: string;
  device_instance?: string;
  device_address?: string;
  point_count: number;
  poll_count: number;
  poll_resource_count?: number;
  points: JsonApiPoint[];
};

type ContextTarget =
  | { kind: "device"; device: JsonApiDevice }
  | { kind: "point"; device: JsonApiDevice; point: JsonApiPoint }
  | null;

type Props = {
  devices: JsonApiDevice[];
  selectedPointIds?: Set<string>;
  onTogglePointSelection?: (pointId: string, selected: boolean) => void;
  onToggleDeviceSelection?: (device: JsonApiDevice, selected: boolean) => void;
  onToggleTypeSelection?: (device: JsonApiDevice, typeName: string, points: JsonApiPoint[], selected: boolean) => void;
  onRefreshDevice?: (device: JsonApiDevice) => void;
  onRefreshPoint?: (device: JsonApiDevice, point: JsonApiPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onSetDevicePoll?: (device: JsonApiDevice, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
  onDeleteDevice?: (device: JsonApiDevice) => void;
  onCopy?: (text: string) => void;
};

function groupPoints(points: JsonApiPoint[]): Map<string, JsonApiPoint[]> {
  const groups = new Map<string, JsonApiPoint[]>();
  for (const p of points) {
    const key = p.method || "GET";
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

function selectionState(ids: string[], selected: Set<string>): "none" | "some" | "all" {
  if (!ids.length) return "none";
  const n = ids.filter((id) => selected.has(id)).length;
  if (n === 0) return "none";
  if (n === ids.length) return "all";
  return "some";
}

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname + (u.search || "");
  } catch {
    return url;
  }
}

export default function JsonApiPointsTree({
  devices,
  selectedPointIds = new Set(),
  onTogglePointSelection,
  onToggleDeviceSelection,
  onToggleTypeSelection,
  onRefreshDevice,
  onRefreshPoint,
  onSetPointPoll,
  onSetDevicePoll,
  onDeletePoint,
  onDeleteDevice,
  onCopy,
}: Props) {
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(() => new Set());
  const [menu, setMenu] = useState<{ x: number; y: number; target: ContextTarget } | null>(null);

  const sorted = useMemo(() => [...devices].sort((a, b) => a.host.localeCompare(b.host)), [devices]);

  function toggleDevice(key: string) {
    setExpandedDevices((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
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

  function expandAll() {
    setExpandedDevices(new Set(sorted.map((d) => d.device_key)));
    const typeKeys: string[] = [];
    for (const dev of sorted) {
      for (const typeName of groupPoints(dev.points).keys()) {
        typeKeys.push(`${dev.device_key}:${typeName}`);
      }
    }
    setExpandedTypes(new Set(typeKeys));
  }

  function collapseAll() {
    setExpandedDevices(new Set());
    setExpandedTypes(new Set());
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
        onSetDevicePoll,
        onDeleteDevice,
        onCopy,
      });
    }
    return buildPointContextMenuItems({
      device: t.device,
      point: t.point,
      onRefreshPoint,
      onSetPointPoll,
      onDeletePoint,
      onCopy,
    });
  }

  if (!sorted.length) {
    return (
      <div className="bacnet-tree-empty">
        <p className="muted">No JSON API endpoints saved yet.</p>
        <p className="muted">
          Try <strong>Read &amp; store</strong> with{" "}
          <code>https://jsonplaceholder.typicode.com/todos/1</code> and json path <code>title</code>.
        </p>
      </div>
    );
  }

  const selectionEnabled = Boolean(onTogglePointSelection);

  return (
    <div className="bacnet-tree">
      <div className="bacnet-tree-toolbar">
        <button type="button" className="secondary-btn" onClick={expandAll}>
          Expand all
        </button>
        <button type="button" className="secondary-btn" onClick={collapseAll}>
          Collapse all
        </button>
      </div>
      {sorted.map((dev) => {
        const devOpen = expandedDevices.has(dev.device_key);
        const typeGroups = groupPoints(dev.points);
        const devPointIds = dev.points.map((p) => p.point_id);
        const devSel = selectionState(devPointIds, selectedPointIds);
        return (
          <div key={dev.device_key} className="bacnet-tree-device">
            <button
              type="button"
              className="bacnet-tree-device-head"
              onClick={() => toggleDevice(dev.device_key)}
              onContextMenu={(e) => openMenu(e, { kind: "device", device: dev })}
            >
              {selectionEnabled ? (
                <input
                  type="checkbox"
                  className="bacnet-tree-select"
                  aria-label={`Select all endpoints on ${dev.host}`}
                  checked={devSel === "all"}
                  ref={(el) => {
                    if (el) el.indeterminate = devSel === "some";
                  }}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => onToggleDeviceSelection?.(dev, e.target.checked)}
                />
              ) : null}
              <span className="bacnet-tree-chevron">{devOpen ? "▾" : "▸"}</span>
              <span className="bacnet-tree-device-icon" aria-hidden>
                🌐
              </span>
              <span className="bacnet-tree-device-title">
                <strong>{dev.host}</strong>
              </span>
              <span className="badge">
                {dev.point_count} sensor{dev.point_count === 1 ? "" : "s"}
              </span>
              {dev.poll_count > 0 ? (
                <span className="badge poll-badge">
                  {dev.poll_resource_count ?? 1} HTTP poll{(dev.poll_resource_count ?? 1) === 1 ? "" : "s"}
                </span>
              ) : null}
            </button>
            {devOpen ? (
              <div className="bacnet-tree-device-body">
                {[...typeGroups.entries()].map(([typeName, pts]) => {
                  const typeKey = `${dev.device_key}:${typeName}`;
                  const typeOpen = expandedTypes.has(typeKey);
                  const typeIds = pts.map((p) => p.point_id);
                  const typeSel = selectionState(typeIds, selectedPointIds);
                  return (
                    <div key={typeKey} className="bacnet-tree-type">
                      <button type="button" className="bacnet-tree-type-head" onClick={() => toggleType(typeKey)}>
                        {selectionEnabled ? (
                          <input
                            type="checkbox"
                            className="bacnet-tree-select"
                            checked={typeSel === "all"}
                            ref={(el) => {
                              if (el) el.indeterminate = typeSel === "some";
                            }}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => onToggleTypeSelection?.(dev, typeName, pts, e.target.checked)}
                          />
                        ) : null}
                        <span className="bacnet-tree-chevron">{typeOpen ? "▾" : "▸"}</span>
                        <span className="bacnet-tree-type-label">{typeName}</span>
                        <span className="badge">{pts.length}</span>
                      </button>
                      {typeOpen ? (
                        <ul className="bacnet-tree-points">
                          {pts.map((p) => {
                            const showVal = String(p.present_value ?? "") !== "";
                            return (
                              <li key={p.point_id}>
                                <div
                                  className={`bacnet-tree-point-row${selectedPointIds.has(p.point_id) ? " bacnet-tree-point-selected" : ""}`}
                                  onContextMenu={(e) => openMenu(e, { kind: "point", device: dev, point: p })}
                                >
                                  {selectionEnabled ? (
                                    <input
                                      type="checkbox"
                                      className="bacnet-tree-select"
                                      checked={selectedPointIds.has(p.point_id)}
                                      onChange={(e) => onTogglePointSelection?.(p.point_id, e.target.checked)}
                                    />
                                  ) : null}
                                  <code title={p.url}>{shortUrl(p.url)}</code>
                                  <span className="bacnet-tree-point-name">
                                    {p.label}
                                    {p.json_path ? <span className="muted"> → {p.json_path}</span> : null}
                                  </span>
                                  {showVal ? (
                                    <span className="badge pv-badge">{p.present_value}</span>
                                  ) : p.enabled ? (
                                    <span className="badge muted-badge">no sample</span>
                                  ) : null}
                                  {p.enabled ? (
                                    <span className="badge poll-badge">⏱ {p.poll_label || `${p.poll_interval_s}s`}</span>
                                  ) : (
                                    <span className="badge muted-badge">idle</span>
                                  )}
                                </div>
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
