/** Tag / role helpers — equipment and points classified by stamps, never by fixture ids. */

export const GENERIC = new Set(["point", "his", "cur", "writable"]);

export function tagsOf(point) {
  return point.tags || [];
}

export function has(point, ...need) {
  const tags = tagsOf(point);
  return need.every((t) => tags.includes(t));
}

export function roleOf(point) {
  return point.role || "";
}

export function isTemp(point) {
  if (has(point, "temp")) return true;
  const role = roleOf(point);
  return (
    role.endsWith("_t") ||
    role === "oa_t" ||
    role === "sat" ||
    role === "mat" ||
    role === "rat" ||
    role === "zone_t"
  );
}

export function isRH(point) {
  return has(point, "humidity") || roleOf(point).includes("humidity");
}

export function isBoolRole(point) {
  if (point.kind === "Bool") return true;
  const role = roleOf(point);
  return role.endsWith("_status") || role.endsWith("_cmd") || role === "occ_mode";
}

export function displayName(point) {
  const tags = tagsOf(point).filter((t) => !GENERIC.has(t) && t !== "sensor");
  if (tags.length) return tags.join(" ");
  return point.dis || point.column || point.role || "point";
}

export function unitLabel(point) {
  return point.unit || "";
}
