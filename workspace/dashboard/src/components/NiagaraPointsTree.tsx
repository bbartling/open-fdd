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
  onToggleTypeSelection?: (device: NiagaraDevice, typeName: string, points: NiagaraPoint[], selected: boolean) => void;
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

function groupPoints(points: NiagaraPoint[]): Map<string, NiagaraPoint[]> {
  const groups = new Map<string, NiagaraPoint[]>();
  for (const p of points) {
    const key = p.kind || p.value_type || p.type_spec || "points";
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

function stationHostLabel(url: string): string {
  const raw = String(url ?? "").trim();
  if (!raw) return "";
  try {
    return new URL(raw).host;
  } catch {
    return raw.replace(/^https?:\/\//i, "").replace(/\/.*$/, "");
  }
}

function isNiagaraStatusOk(status?: string, ok?: boolean): boolean {
  if (ok === false) return false;
  if (!status) return true;
  const s = status.toLowerCase();
  return s.includes("{ok}") || s === "ok";
}

function formatPointValue(point: NiagaraPoint): string {
  const raw = point.display_value ?? point.value;
  const text = formatNiagaraValue(raw);
  if (text === "—" || !point.units) return text;
  return `${text} ${point.units}`;
}

export default function NiagaraPointsTree({
  devices,
  selectedPointOrds = new Set(),
  onTogglePointSelection,
  onToggleDeviceSelection,
  onToggleTypeSelection,
  onRefreshDevice,
  onRefreshPoint,
  onDiscoverDevice,
  onCopy,
}: Props) {
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(() => new Set());
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

  function toggleType(key: string) {
    setExpandedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function expandAll() {
    setExpandedDevices(new Set(sorted.map((d) => d.station_id)));
    const typeKeys: string[] = [];
    for (const dev of sorted) {
      for (const typeName of groupPoints(dev.points).keys()) {
        typeKeys.push(`${dev.station_id}:${typeName}`);
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
    return (
      <div className="bacnet-tree-empty">
        <p className="muted">No discovered Niagara points yet.</p>
        <p className="muted">
          Add a station under <strong>Station connection</strong>, test the connection, then click{" "}
          <strong>Discover points</strong>.
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
      {sorted.map((device) => {
        const devOpen = expandedDevices.has(device.station_id);
        const typeGroups = groupPoints(device.points);
        const pointOrds = device.points.map((p) => p.point_ord);
        const devSel = selectionState(pointOrds, selectedPointOrds);
        const host = stationHostLabel(device.station_url);
        return (
          <div key={device.station_id} className="bacnet-tree-device">
            <button
              type="button"
              className="bacnet-tree-device-head"
              onClick={() => toggleDevice(device.station_id)}
              onContextMenu={(e) => openMenu(e, { kind: "device", device })}
              title={device.station_url || undefined}
            >
              {selectionEnabled ? (
                <input
                  type="checkbox"
                  className="bacnet-tree-select"
                  aria-label={`Select all points on ${device.station_name || device.station_id}`}
                  checked={devSel === "all"}
                  ref={(el) => {
                    if (el) el.indeterminate = devSel === "some";
                  }}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => onToggleDeviceSelection?.(device, e.target.checked)}
                />
              ) : null}
              <span className="bacnet-tree-chevron">{devOpen ? "▾" : "▸"}</span>
              <span className="bacnet-tree-device-icon" aria-hidden>
                📡
              </span>
              <span className="bacnet-tree-device-title">
                <strong>{device.station_name || device.station_id}</strong>
                {host ? <span className="muted"> @ {host}</span> : null}
              </span>
              <span className="badge">{device.point_count} pts</span>
              {device.poll_running ? (
                <span className="badge poll-badge" title="Background poll running">
                  ⏱ polling
                </span>
              ) : null}
            </button>
            {devOpen ? (
              <div className="bacnet-tree-device-body">
                {[...typeGroups.entries()].map(([typeName, pts]) => {
                  const typeKey = `${device.station_id}:${typeName}`;
                  const typeOpen = expandedTypes.has(typeKey);
                  const typeOrds = pts.map((p) => p.point_ord);
                  const typeSel = selectionState(typeOrds, selectedPointOrds);
                  return (
                    <div key={typeKey} className="bacnet-tree-type">
                      <button type="button" className="bacnet-tree-type-head" onClick={() => toggleType(typeKey)}>
                        {selectionEnabled ? (
                          <input
                            type="checkbox"
                            className="bacnet-tree-select"
                            aria-label={`Select all ${typeName} on ${device.station_name || device.station_id}`}
                            checked={typeSel === "all"}
                            ref={(el) => {
                              if (el) el.indeterminate = typeSel === "some";
                            }}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => onToggleTypeSelection?.(device, typeName, pts, e.target.checked)}
                          />
                        ) : null}
                        <span className="bacnet-tree-chevron">{typeOpen ? "▾" : "▸"}</span>
                        <span className="bacnet-tree-type-label">{typeName}</span>
                        <span className="badge">{pts.length}</span>
                      </button>
                      {typeOpen ? (
                        <ul className="bacnet-tree-points">
                          {pts.map((point) => {
                            const valueText = formatPointValue(point);
                            const hasValue = valueText !== "—";
                            const statusOk = isNiagaraStatusOk(point.status, point.ok);
                            return (
                              <li key={point.point_ord}>
                                <div
                                  className={`bacnet-tree-point-row${
                                    selectedPointOrds.has(point.point_ord) ? " bacnet-tree-point-selected" : ""
                                  }`}
                                  onContextMenu={(e) => openMenu(e, { kind: "point", device, point })}
                                >
                                  {selectionEnabled ? (
                                    <input
                                      type="checkbox"
                                      className="bacnet-tree-select"
                                      aria-label={`Select ${point.point_name}`}
                                      checked={selectedPointOrds.has(point.point_ord)}
                                      onChange={(e) => onTogglePointSelection?.(point.point_ord, e.target.checked)}
                                    />
                                  ) : null}
                                  <span className="bacnet-tree-point-name">{point.point_name}</span>
                                  {point.writable ? (
                                    <span
                                      className="badge commandable-badge"
                                      title="Writable on station — read-only in Open-FDD"
                                    >
                                      cmd
                                    </span>
                                  ) : null}
                                  {!statusOk ? (
                                    <span className="badge operator-override-badge" title={point.status || "Point fault"}>
                                      fault
                                    </span>
                                  ) : null}
                                  {hasValue ? (
                                    <span className="badge pv-badge" title="Live value">
                                      {valueText}
                                    </span>
                                  ) : (
                                    <span className="badge muted-badge" title="No value read yet">
                                      no sample
                                    </span>
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
      {menu ? <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={() => setMenu(null)} /> : null}
    </div>
  );
}

export type { NiagaraDevice, NiagaraPoint };
