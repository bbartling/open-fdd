import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import type { NiagaraDevice, NiagaraPoint } from "../lib/niagara-api";
import { buildDeviceContextMenuItems, buildPointContextMenuItems, formatNiagaraValue } from "../lib/niagaraTreeMenu";

type ContextTarget =
  | { kind: "device"; device: NiagaraDevice }
  | { kind: "point"; device: NiagaraDevice; point: NiagaraPoint }
  | null;

type Props = {
  devices: NiagaraDevice[];
  selectedPointOrds?: Set<string>;
  onTogglePointSelection?: (pointOrd: string, selected: boolean) => void;
  onToggleDeviceSelection?: (device: NiagaraDevice, selected: boolean) => void;
  onRefreshDevice?: (device: NiagaraDevice) => void;
  onRefreshPoint?: (device: NiagaraDevice, point: NiagaraPoint) => void;
  onDiscoverDevice?: (device: NiagaraDevice) => void;
  onCopy?: (text: string) => void;
};

function selectionState(ids: string[], selected: Set<string>): "none" | "some" | "all" {
  if (!ids.length) return "none";
  const n = ids.filter((id) => selected.has(id)).length;
  if (n === 0) return "none";
  if (n === ids.length) return "all";
  return "some";
}

export default function NiagaraPointsTree({
  devices,
  selectedPointOrds = new Set(),
  onTogglePointSelection,
  onToggleDeviceSelection,
  onRefreshDevice,
  onRefreshPoint,
  onDiscoverDevice,
  onCopy,
}: Props) {
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [menu, setMenu] = useState<{ x: number; y: number; target: ContextTarget } | null>(null);

  const sorted = useMemo(
    () => [...devices].sort((a, b) => (a.station_name || a.station_id).localeCompare(b.station_name || b.station_id)),
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

  function expandAll() {
    setExpandedDevices(new Set(sorted.map((d) => d.station_id)));
  }

  function collapseAll() {
    setExpandedDevices(new Set());
  }

  function openMenu(e: React.MouseEvent, target: ContextTarget) {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, target });
  }

  const menuItems = useMemo(() => {
    if (!menu?.target) return [];
    if (menu.target.kind === "device") {
      return buildDeviceContextMenuItems({
        device: menu.target.device,
        onRefreshDevice,
        onDiscover: onDiscoverDevice,
        onCopy,
      });
    }
    return buildPointContextMenuItems({
      point: menu.target.point,
      device: menu.target.device,
      onRefreshPoint,
      onCopy,
    });
  }, [menu, onCopy, onDiscoverDevice, onRefreshDevice, onRefreshPoint]);

  if (!sorted.length) {
    return <p className="muted">No discovered Niagara points — add a station, test connection, then Discover.</p>;
  }

  return (
    <div className="bacnet-points-tree">
      <div className="row row-spread" style={{ marginBottom: "0.5rem" }}>
        <span className="muted">{sorted.length} station(s)</span>
        <div className="row" style={{ gap: "0.35rem" }}>
          <button type="button" className="secondary-btn" onClick={expandAll}>
            Expand all
          </button>
          <button type="button" className="secondary-btn" onClick={collapseAll}>
            Collapse all
          </button>
        </div>
      </div>
      <ul className="bacnet-tree-list">
        {sorted.map((device) => {
          const expanded = expandedDevices.has(device.station_id);
          const pointOrds = device.points.map((p) => p.point_ord);
          const sel = selectionState(pointOrds, selectedPointOrds);
          return (
            <li key={device.station_id} className="bacnet-tree-device">
              <div
                className="bacnet-tree-row device-row"
                onContextMenu={(e) => openMenu(e, { kind: "device", device })}
              >
                <button type="button" className="bacnet-tree-toggle" onClick={() => toggleDevice(device.station_id)}>
                  {expanded ? "▾" : "▸"}
                </button>
                {onToggleDeviceSelection ? (
                  <input
                    type="checkbox"
                    checked={sel === "all"}
                    ref={(el) => {
                      if (el) el.indeterminate = sel === "some";
                    }}
                    onChange={(e) => onToggleDeviceSelection(device, e.target.checked)}
                    aria-label={`Select all points on ${device.station_name}`}
                  />
                ) : null}
                <span className="bacnet-tree-device-label">
                  {device.station_name || device.station_id}
                  <span className="muted"> — {device.station_url}</span>
                </span>
                <span className="badge muted-badge">{device.point_count} pt</span>
                {device.poll_running ? <span className="badge poll-badge">⏱ polling</span> : null}
              </div>
              {expanded ? (
                <ul className="bacnet-tree-points">
                  {device.points.map((point) => (
                    <li
                      key={point.point_ord}
                      className="bacnet-tree-row point-row"
                      onContextMenu={(e) => openMenu(e, { kind: "point", device, point })}
                    >
                      {onTogglePointSelection ? (
                        <input
                          type="checkbox"
                          checked={selectedPointOrds.has(point.point_ord)}
                          onChange={(e) => onTogglePointSelection(point.point_ord, e.target.checked)}
                          aria-label={`Select ${point.point_name}`}
                        />
                      ) : null}
                      <span className="bacnet-tree-point-name">{point.point_name}</span>
                      <span className="badge pv-badge">{formatNiagaraValue(point.display_value ?? point.value)}</span>
                      {point.units ? <span className="badge muted-badge">{point.units}</span> : null}
                      {point.status ? <span className="badge muted-badge">{point.status}</span> : null}
                      {point.writable ? <span className="badge muted-badge">writable (read-only UI)</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
      {menu ? (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={() => setMenu(null)} />
      ) : null}
    </div>
  );
}

export type { NiagaraDevice, NiagaraPoint };
