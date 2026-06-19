import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import type { NiagaraPoint } from "../lib/niagara-api";
import {
  brickBindingHint,
  type OrganizedBuilding,
  type OrganizedDevice,
  type OrganizedStation,
} from "../lib/niagaraCommissionProfile";
import { buildDeviceContextMenuItems, buildPointContextMenuItems, formatNiagaraValue } from "../lib/niagaraTreeMenu";
import type { NiagaraDevice } from "../lib/niagara-api";

type ContextTarget =
  | { kind: "building"; building: OrganizedBuilding }
  | { kind: "device"; building: OrganizedBuilding; device: OrganizedDevice }
  | { kind: "point"; building: OrganizedBuilding; device: OrganizedDevice; point: NiagaraPoint }
  | null;

type Props = {
  station: OrganizedStation;
  selectedPointOrds?: Set<string>;
  onTogglePointSelection?: (pointOrd: string, selected: boolean) => void;
  onToggleDeviceSelection?: (points: NiagaraPoint[], selected: boolean) => void;
  onRefreshPoint?: (point: NiagaraPoint) => void;
  onDiscoverDevice?: (folderOrd: string) => void;
  onRemoveBuilding?: (buildingId: string) => void;
  onRemoveDevice?: (deviceId: string) => void;
  onCopy?: (text: string) => void;
};

function groupPoints(points: NiagaraPoint[]): Map<string, NiagaraPoint[]> {
  const groups = new Map<string, NiagaraPoint[]>();
  for (const p of points) {
    const key = p.kind || p.value_type || p.type_spec || "points";
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

function stationHostLabel(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//i, "").replace(/\/.*$/, "");
  }
}

function toLegacyDevice(station: OrganizedStation, device: OrganizedDevice): NiagaraDevice {
  return {
    station_id: station.station_id,
    station_name: station.station_name,
    station_url: station.station_url,
    point_count: device.points.length,
    poll_running: station.poll_running,
    points: device.points,
  };
}

export default function NiagaraCommissionTree({
  station,
  selectedPointOrds = new Set(),
  onTogglePointSelection,
  onToggleDeviceSelection,
  onRefreshPoint,
  onDiscoverDevice,
  onRemoveBuilding,
  onRemoveDevice,
  onCopy,
}: Props) {
  const [expandedBuildings, setExpandedBuildings] = useState<Set<string>>(() => new Set());
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(() => new Set());
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(() => new Set());
  const [stationOpen, setStationOpen] = useState(true);
  const [menu, setMenu] = useState<{ x: number; y: number; target: ContextTarget } | null>(null);

  const host = stationHostLabel(station.station_url);
  const totalPoints = useMemo(
    () => station.buildings.reduce((n, b) => n + b.point_count, 0) + station.unassigned.length,
    [station],
  );

  function expandAll() {
    setStationOpen(true);
    setExpandedBuildings(new Set(station.buildings.map((b) => b.building.id)));
    setExpandedDevices(
      new Set(station.buildings.flatMap((b) => b.devices.map((d) => d.device.id))),
    );
    const typeKeys: string[] = [];
    for (const b of station.buildings) {
      for (const d of b.devices) {
        for (const typeName of groupPoints(d.points).keys()) {
          typeKeys.push(`${d.device.id}:${typeName}`);
        }
      }
    }
    setExpandedTypes(new Set(typeKeys));
  }

  function collapseAll() {
    setExpandedBuildings(new Set());
    setExpandedDevices(new Set());
    setExpandedTypes(new Set());
  }

  const menuItems = useMemo(() => {
    if (!menu?.target) return [];
    if (menu.target.kind === "building") {
      return [
        {
          id: "remove-building",
          label: "Remove building from profile",
          onClick: () => onRemoveBuilding?.(menu.target!.building.building.id),
        },
        {
          id: "copy-ord",
          label: "Copy building ORD",
          onClick: () => onCopy?.(menu.target!.building.building.folder_ord),
        },
      ];
    }
    if (menu.target.kind === "device") {
      const { device, building } = menu.target;
      const legacy = toLegacyDevice(station, device);
      return [
        ...buildDeviceContextMenuItems({
          device: legacy,
          onDiscover: () => onDiscoverDevice?.(device.device.folder_ord),
          onCopy,
        }),
        {
          id: "brick-hint",
          label: brickBindingHint(device.device, building.building),
          disabled: true,
          onClick: () => undefined,
        },
        {
          id: "remove-device",
          label: "Remove device from profile",
          onClick: () => onRemoveDevice?.(device.device.id),
        },
      ];
    }
    const { point, device, building } = menu.target;
    return buildPointContextMenuItems({
      point,
      device: toLegacyDevice(station, device),
      onRefreshPoint: (_, p) => onRefreshPoint?.(p),
      onCopy,
    });
  }, [menu, onCopy, onDiscoverDevice, onRefreshPoint, onRemoveBuilding, onRemoveDevice, station]);

  if (!station.buildings.length && !station.unassigned.length) {
    return (
      <div className="bacnet-tree-empty">
        <p className="muted">No commission profile yet.</p>
        <p className="muted">
          Browse the station tree, <strong>right-click</strong> a folder → <strong>Add as building</strong>, then add
          device folders (e.g. BENS BENCHTEST BOX). Discover points to populate the tree for BRICK bindings.
        </p>
      </div>
    );
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

      <div className="bacnet-tree-device">
        <button type="button" className="bacnet-tree-device-head" onClick={() => setStationOpen((v) => !v)}>
          <span className="bacnet-tree-chevron">{stationOpen ? "▾" : "▸"}</span>
          <span className="bacnet-tree-device-icon" aria-hidden>
            📡
          </span>
          <span className="bacnet-tree-device-title">
            <strong>{station.station_name}</strong>
            {host ? <span className="muted"> @ {host}</span> : null}
          </span>
          <span className="badge">{totalPoints} pts</span>
          {station.poll_running ? <span className="badge poll-badge">⏱ polling</span> : null}
        </button>
        {stationOpen ? (
          <div className="bacnet-tree-device-body">
            {station.buildings.map((bRow) => {
              const bOpen = expandedBuildings.has(bRow.building.id);
              return (
                <div key={bRow.building.id} className="bacnet-tree-type niagara-commission-building">
                  <button
                    type="button"
                    className="bacnet-tree-type-head"
                    onClick={() =>
                      setExpandedBuildings((prev) => {
                        const next = new Set(prev);
                        if (next.has(bRow.building.id)) next.delete(bRow.building.id);
                        else next.add(bRow.building.id);
                        return next;
                      })
                    }
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setMenu({ x: e.clientX, y: e.clientY, target: { kind: "building", building: bRow } });
                    }}
                  >
                    <span className="bacnet-tree-chevron">{bOpen ? "▾" : "▸"}</span>
                    <span className="bacnet-tree-type-label">🏢 {bRow.building.label}</span>
                    <span className="badge">{bRow.point_count} pts</span>
                    {bRow.building.site_id ? <span className="badge muted-badge">site:{bRow.building.site_id}</span> : null}
                  </button>
                  {bOpen ? (
                    <div className="bacnet-tree-device-body">
                      {bRow.devices.map((dRow) => {
                        const dOpen = expandedDevices.has(dRow.device.id);
                        const typeGroups = groupPoints(dRow.points);
                        return (
                          <div key={dRow.device.id} className="bacnet-tree-device niagara-commission-device">
                            <button
                              type="button"
                              className="bacnet-tree-device-head"
                              onClick={() =>
                                setExpandedDevices((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(dRow.device.id)) next.delete(dRow.device.id);
                                  else next.add(dRow.device.id);
                                  return next;
                                })
                              }
                              onContextMenu={(e) => {
                                e.preventDefault();
                                setMenu({
                                  x: e.clientX,
                                  y: e.clientY,
                                  target: { kind: "device", building: bRow, device: dRow },
                                });
                              }}
                            >
                              <span className="bacnet-tree-chevron">{dOpen ? "▾" : "▸"}</span>
                              <span className="bacnet-tree-device-icon">⚙️</span>
                              <span className="bacnet-tree-device-title">
                                <strong>{dRow.device.label}</strong>
                                <span className="muted" style={{ display: "block", fontSize: "0.82em" }}>
                                  {dRow.device.equipment_id ? `equipment: ${dRow.device.equipment_id}` : null}
                                </span>
                              </span>
                              <span className="badge">{dRow.points.length} pts</span>
                            </button>
                            {dOpen ? (
                              <div className="bacnet-tree-device-body">
                                {[...typeGroups.entries()].map(([typeName, pts]) => {
                                  const typeKey = `${dRow.device.id}:${typeName}`;
                                  const typeOpen = expandedTypes.has(typeKey);
                                  return (
                                    <div key={typeKey} className="bacnet-tree-type">
                                      <button
                                        type="button"
                                        className="bacnet-tree-type-head"
                                        onClick={() =>
                                          setExpandedTypes((prev) => {
                                            const next = new Set(prev);
                                            if (next.has(typeKey)) next.delete(typeKey);
                                            else next.add(typeKey);
                                            return next;
                                          })
                                        }
                                      >
                                        <span className="bacnet-tree-chevron">{typeOpen ? "▾" : "▸"}</span>
                                        <span className="bacnet-tree-type-label">{typeName}</span>
                                        <span className="badge">{pts.length}</span>
                                      </button>
                                      {typeOpen ? (
                                        <ul className="bacnet-tree-points">
                                          {pts.map((p) => (
                                            <li
                                              key={p.point_ord}
                                              className={`bacnet-tree-point-row${selectedPointOrds.has(p.point_ord) ? " bacnet-tree-point-selected" : ""}`}
                                              onContextMenu={(e) => {
                                                e.preventDefault();
                                                setMenu({
                                                  x: e.clientX,
                                                  y: e.clientY,
                                                  target: { kind: "point", building: bRow, device: dRow, point: p },
                                                });
                                              }}
                                            >
                                              {onTogglePointSelection ? (
                                                <input
                                                  type="checkbox"
                                                  checked={selectedPointOrds.has(p.point_ord)}
                                                  onChange={(e) => onTogglePointSelection(p.point_ord, e.target.checked)}
                                                />
                                              ) : null}
                                              <span className="bacnet-tree-point-name">{p.point_name}</span>
                                              <span className="muted">{formatNiagaraValue(p.display_value ?? p.value)}</span>
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
                    </div>
                  ) : null}
                </div>
              );
            })}
            {station.unassigned.length ? (
              <div className="panel-warn" style={{ margin: "0.5rem 0", padding: "0.5rem" }}>
                <strong>{station.unassigned.length}</strong> point(s) not matched to a device folder — right-click browse
                nodes to add devices or widen points_root.
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {menu ? <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={() => setMenu(null)} /> : null}
    </div>
  );
}
