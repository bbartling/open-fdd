export type WhoisDeviceRow = {
  "i-am-device-identifier"?: string;
  "device-address"?: string;
  "device-description"?: string;
  [key: string]: unknown;
};

export type PointDiscoveryObjectRow = {
  object_identifier: string;
  name: string;
  commandable: boolean;
};

export type InventoryPoint = {
  object_identifier: string;
  object_name: string;
  description: string;
  present_value: string;
  units: string;
  point_id: string;
};

export type InventoryDevice = {
  device_instance: string;
  device_address: string;
  point_count?: number;
  points: InventoryPoint[];
};

export function parseDeviceInstanceFromIAmIdentifier(raw: string): number | null {
  const s = (raw || "").trim();
  if (!s) return null;
  const dm = s.match(/device\D*(\d+)/i);
  if (dm) {
    const n = Number(dm[1]);
    if (Number.isFinite(n) && n >= 0 && n <= 4194303) return n;
  }
  const nums = s.match(/\d+/g);
  if (!nums?.length) return null;
  for (let i = nums.length - 1; i >= 0; i--) {
    const n = Number(nums[i]);
    if (Number.isFinite(n) && n >= 0 && n <= 4194303) return n;
  }
  return null;
}

export function parseDeviceInstanceFromWhoisRow(row: WhoisDeviceRow): number | null {
  return parseDeviceInstanceFromIAmIdentifier(row["i-am-device-identifier"] ?? "");
}

export function extractWhoisDevices(res: unknown): WhoisDeviceRow[] {
  if (!res || typeof res !== "object") return [];
  const body = res as Record<string, unknown>;
  if (Array.isArray(body.devices)) {
    return body.devices as WhoisDeviceRow[];
  }
  const nested =
    (body.result as { data?: { devices?: unknown } } | undefined)?.data?.devices ??
    (body.data as { devices?: unknown } | undefined)?.devices;
  if (Array.isArray(nested)) return nested as WhoisDeviceRow[];
  return [];
}

export function extractPointDiscoveryObjects(result: unknown): PointDiscoveryObjectRow[] {
  if (!result || typeof result !== "object") return [];
  const r = result as { objects?: unknown[] };
  if (!Array.isArray(r.objects)) return [];
  return r.objects.map((o) => {
    const row = o as Record<string, unknown>;
    return {
      object_identifier: String(row.object_identifier ?? "—"),
      name: String(row.name ?? "—"),
      commandable: Boolean(row.commandable),
    };
  });
}
