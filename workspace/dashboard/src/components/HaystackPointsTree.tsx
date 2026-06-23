import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import { buildDeviceContextMenuItems, buildPointContextMenuItems } from "../lib/haystackTreeMenu";

export type HaystackPoint = {
  point_id: string;
  label: string;
  haystack_id: string;
  tags?: Record<string, unknown>;
  kind?: unknown;
  unit?: unknown;
  curVal?: unknown;
  present_value?: string;
  enabled: boolean;
  poll_interval_s: number;
  poll_label: string;
  last_read_at?: string;
  mapping_status?: string;
};

export type HaystackDevice = {
  device_key: string;
  host: string;
  site_id: string;
  point_count: number;
  poll_count: number;
  points: HaystackPoint[];
};

type ContextTarget =
  | { kind: "device"; device: HaystackDevice }
  | { kind: "point"; device: HaystackDevice; point: HaystackPoint }
  | null;

type Props = {
  devices: HaystackDevice[];
  onSelectPoint?: (device: HaystackDevice, point: HaystackPoint) => void;
  onSelectDevice?: (device: HaystackDevice) => void;
  onRefreshSite?: (device: HaystackDevice) => void;
  onRefreshPoint?: (device: HaystackDevice, point: HaystackPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onSetDevicePoll?: (device: HaystackDevice, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
  onDeleteDevice?: (device: HaystackDevice) => void;
  onCopy?: (text: string) => void;
};

export default function HaystackPointsTree({
  devices,
  onSelectPoint,
  onSelectDevice,
  onRefreshSite,
  onRefreshPoint,
  onSetPointPoll,
  onSetDevicePoll,
  onDeletePoint,
  onDeleteDevice,
  onCopy,
}: Props) {
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [menu, setMenu] = useState<{ x: number; y: number; target: ContextTarget } | null>(null);
  const sorted = useMemo(() => [...devices].sort((a, b) => a.site_id.localeCompare(b.site_id)), [devices]);

  function expandAll() {
    setExpandedDevices(new Set(sorted.map((d) => d.device_key)));
  }

  function collapseAll() {
    setExpandedDevices(new Set());
  }

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
      {!sorted.length ? (
        <div className="bacnet-tree-empty">
          <p className="muted">No Haystack sites loaded.</p>
        </div>
      ) : null}
      {sorted.map((dev) => {
        const open = expandedDevices.has(dev.device_key);
        return (
          <div key={dev.device_key} className="bacnet-tree-device">
            <button
              type="button"
              className="bacnet-tree-device-head"
              onClick={() => {
                setExpandedDevices((prev) => {
                  const next = new Set(prev);
                  if (next.has(dev.device_key)) next.delete(dev.device_key);
                  else next.add(dev.device_key);
                  return next;
                });
                onSelectDevice?.(dev);
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                setMenu({ x: e.clientX, y: e.clientY, target: { kind: "device", device: dev } });
              }}
            >
              <span className="bacnet-tree-chevron">{open ? "▾" : "▸"}</span>
              <span className="bacnet-tree-device-icon" aria-hidden>
                🏢
              </span>
              <span className="bacnet-tree-device-title">
                <strong>{dev.site_id}</strong>
              </span>
              <span className="badge">{dev.point_count} pts</span>
            </button>
            {open ? (
              <ul className="bacnet-tree-points">
                {dev.points.map((p) => (
                  <li key={p.point_id}>
                    <button
                      type="button"
                      className="bacnet-tree-point-row point-select-btn"
                      onClick={() => onSelectPoint?.(dev, p)}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        setMenu({ x: e.clientX, y: e.clientY, target: { kind: "point", device: dev, point: p } });
                      }}
                    >
                      <code>{p.haystack_id}</code>
                      <span className="bacnet-tree-point-name">{p.label}</span>
                      <span className={`badge ${p.mapping_status === "mapped" ? "mapped-badge" : "muted-badge"}`}>
                        {p.mapping_status ?? "unmapped"}
                      </span>
                      {p.enabled ? <span className="badge poll-badge">⏱ {p.poll_label}</span> : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
      {menu ? (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={
            menu.target?.kind === "device"
              ? buildDeviceContextMenuItems({
                  device: menu.target.device,
                  onRefreshSite,
                  onSetDevicePoll,
                  onDeleteDevice,
                  onCopy,
                })
              : menu.target?.kind === "point"
                ? buildPointContextMenuItems({
                    device: menu.target.device,
                    point: menu.target.point,
                    onRefreshPoint,
                    onSetPointPoll,
                    onDeletePoint,
                    onCopy,
                  })
                : []
          }
          onClose={() => setMenu(null)}
        />
      ) : null}
    </div>
  );
}
