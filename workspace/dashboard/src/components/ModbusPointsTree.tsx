import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import { buildDeviceContextMenuItems, buildPointContextMenuItems } from "../lib/modbusTreeMenu";

export type ModbusPoint = {
  point_id: string;
  label: string;
  register_address: string;
  function: string;
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

export type ModbusDevice = {
  device_key: string;
  host: string;
  port: string;
  unit_id: string;
  device_instance?: string;
  device_address?: string;
  point_count: number;
  poll_count: number;
  points: ModbusPoint[];
};

type ContextTarget =
  | { kind: "device"; device: ModbusDevice }
  | { kind: "point"; device: ModbusDevice; point: ModbusPoint }
  | null;

type Props = {
  devices: ModbusDevice[];
  selectedPointIds?: Set<string>;
  onTogglePointSelection?: (pointId: string, selected: boolean) => void;
  onToggleDeviceSelection?: (device: ModbusDevice, selected: boolean) => void;
  onToggleTypeSelection?: (device: ModbusDevice, typeName: string, points: ModbusPoint[], selected: boolean) => void;
  onRefreshDevice?: (device: ModbusDevice) => void;
  onRefreshPoint?: (device: ModbusDevice, point: ModbusPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onSetDevicePoll?: (device: ModbusDevice, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
  onDeleteDevice?: (device: ModbusDevice) => void;
  onCopy?: (text: string) => void;
};

function groupPoints(points: ModbusPoint[]): Map<string, ModbusPoint[]> {
  const groups = new Map<string, ModbusPoint[]>();
  for (const p of points) {
    const key = p.function || "register";
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

export default function ModbusPointsTree({
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

  const sorted = useMemo(
    () => [...devices].sort((a, b) => `${a.host}:${a.port}`.localeCompare(`${b.host}:${b.port}`)),
    [devices],
  );

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
        <p className="muted">No Modbus registers saved yet.</p>
        <p className="muted">
          Use <strong>Read &amp; store</strong> above, or start the fake sensor:{" "}
          <code>./scripts/fake_modbus_temp_server.py --port 5502</code>
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
                  aria-label={`Select all registers on ${dev.host}:${dev.port}`}
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
                🔌
              </span>
              <span className="bacnet-tree-device-title">
                <strong>
                  {dev.host}:{dev.port}
                </strong>
                <span className="muted"> unit {dev.unit_id}</span>
              </span>
              <span className="badge">{dev.point_count} regs</span>
              {dev.poll_count > 0 ? (
                <span className="badge poll-badge">{dev.poll_count} polling</span>
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
                            aria-label={`Select all ${typeName} on ${dev.host}`}
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
                                      aria-label={`Select ${p.label}`}
                                      checked={selectedPointIds.has(p.point_id)}
                                      onChange={(e) => onTogglePointSelection?.(p.point_id, e.target.checked)}
                                    />
                                  ) : null}
                                  <code>
                                    {p.function}@{p.register_address}
                                  </code>
                                  <span className="bacnet-tree-point-name">{p.label}</span>
                                  {showVal ? (
                                    <span className="badge pv-badge" title="Register value">
                                      {p.present_value}
                                      {p.units ? ` ${p.units}` : ""}
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
