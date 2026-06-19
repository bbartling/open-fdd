/** Niagara commission profile — map station folder ORDs to buildings/devices for BRICK + polling. */

import type { NiagaraPoint, NiagaraTreeNode } from "./niagara-api";

export type NiagaraBuilding = {
  id: string;
  label: string;
  folder_ord: string;
  /** Open-FDD / BRICK site scope (defaults to station site) */
  site_id?: string;
  brick_building_id?: string;
};

export type NiagaraCommissionDevice = {
  id: string;
  label: string;
  folder_ord: string;
  building_id: string;
  /** BRICK equipment id for feeds/fedBy and rule bindings */
  equipment_id?: string;
  /** When set, only points under this ORD (e.g. …/points) */
  points_root?: string;
};

export type NiagaraCommissionProfile = {
  version: 1;
  buildings: NiagaraBuilding[];
  devices: NiagaraCommissionDevice[];
};

export type OrganizedDevice = {
  device: NiagaraCommissionDevice;
  points: NiagaraPoint[];
};

export type OrganizedBuilding = {
  building: NiagaraBuilding;
  devices: OrganizedDevice[];
  point_count: number;
};

export type OrganizedStation = {
  station_id: string;
  station_name: string;
  station_url: string;
  buildings: OrganizedBuilding[];
  unassigned: NiagaraPoint[];
  poll_running?: boolean;
};

export function emptyProfile(): NiagaraCommissionProfile {
  return { version: 1, buildings: [], devices: [] };
}

export function slugId(text: string): string {
  return String(text || "item")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48) || "item";
}

export function decodeOrdName(ord: string): string {
  try {
    return decodeURIComponent(String(ord).split("/").pop() || ord).replace(/\$/g, " ");
  } catch {
    return String(ord).split("/").pop() || ord;
  }
}

export function ordChildOf(child: string, parent: string): boolean {
  const c = child.replace(/\/$/, "");
  const p = parent.replace(/\/$/, "");
  if (!p || c === p) return false;
  return c.startsWith(`${p}/`);
}

export function suggestPointsRoot(deviceOrd: string, nodes: NiagaraTreeNode[]): string | undefined {
  const direct = `${deviceOrd.replace(/\/$/, "")}/points`;
  if (nodes.some((n) => n.ord === direct || ordChildOf(n.ord, direct))) return direct;
  const child = nodes.find((n) => ordChildOf(n.ord, deviceOrd) && /\/points$/i.test(n.ord));
  return child?.ord;
}

export function addBuilding(
  profile: NiagaraCommissionProfile,
  node: NiagaraTreeNode,
  opts?: { site_id?: string },
): NiagaraCommissionProfile {
  const folder_ord = node.ord;
  if (profile.buildings.some((b) => b.folder_ord === folder_ord)) return profile;
  const label = node.name || decodeOrdName(folder_ord);
  const building: NiagaraBuilding = {
    id: slugId(label),
    label,
    folder_ord,
    site_id: opts?.site_id,
    brick_building_id: slugId(label),
  };
  return { ...profile, buildings: [...profile.buildings, building] };
}

export function addDevice(
  profile: NiagaraCommissionProfile,
  node: NiagaraTreeNode,
  buildingId: string,
  nodes: NiagaraTreeNode[],
): NiagaraCommissionProfile {
  const folder_ord = node.ord;
  if (profile.devices.some((d) => d.folder_ord === folder_ord)) return profile;
  const label = node.name || decodeOrdName(folder_ord);
  const points_root = suggestPointsRoot(folder_ord, nodes);
  const device: NiagaraCommissionDevice = {
    id: slugId(`${buildingId}-${label}`),
    label,
    folder_ord,
    building_id: buildingId,
    equipment_id: slugId(label),
    points_root,
  };
  return { ...profile, devices: [...profile.devices, device] };
}

export function removeBuilding(profile: NiagaraCommissionProfile, buildingId: string): NiagaraCommissionProfile {
  return {
    ...profile,
    buildings: profile.buildings.filter((b) => b.id !== buildingId),
    devices: profile.devices.filter((d) => d.building_id !== buildingId),
  };
}

export function removeDevice(profile: NiagaraCommissionProfile, deviceId: string): NiagaraCommissionProfile {
  return {
    ...profile,
    devices: profile.devices.filter((d) => d.id !== deviceId),
  };
}

function pointMatchesDevice(point: NiagaraPoint, device: NiagaraCommissionDevice): boolean {
  const ord = point.point_ord || "";
  const root = device.points_root || device.folder_ord;
  return ord === root || ordChildOf(ord, root);
}

export function organizeStationPoints(args: {
  station_id: string;
  station_name: string;
  station_url: string;
  points: NiagaraPoint[];
  profile: NiagaraCommissionProfile;
  poll_running?: boolean;
}): OrganizedStation {
  const { station_id, station_name, station_url, points, profile, poll_running } = args;
  const assigned = new Set<string>();
  const buildings: OrganizedBuilding[] = profile.buildings.map((building) => {
    const devices: OrganizedDevice[] = profile.devices
      .filter((d) => d.building_id === building.id)
      .sort((a, b) => a.label.localeCompare(b.label))
      .map((device) => {
        const devPoints = points.filter((p) => {
          if (!pointMatchesDevice(p, device)) return false;
          assigned.add(p.point_ord);
          return true;
        });
        return { device, points: devPoints };
      });
    const point_count = devices.reduce((n, d) => n + d.points.length, 0);
    return { building, devices, point_count };
  });
  const unassigned = points.filter((p) => !assigned.has(p.point_ord));
  return { station_id, station_name, station_url, buildings, unassigned, poll_running };
}

export function profileSummary(profile: NiagaraCommissionProfile): string {
  return `${profile.buildings.length} building(s), ${profile.devices.length} device(s)`;
}

export function brickBindingHint(device: NiagaraCommissionDevice, building: NiagaraBuilding): string {
  const eq = device.equipment_id || device.label;
  const site = building.site_id || building.brick_building_id || building.label;
  return `site=${site} equipment=${eq} · points under ${device.points_root || device.folder_ord}`;
}
