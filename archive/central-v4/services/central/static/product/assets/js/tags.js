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
  if (/-temp$/.test(role) || role.endsWith("_t")) return true;
  return (
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
  if (point.kind === "Number") return false;
  const role = roleOf(point);
  if (role.endsWith("_status") && point.kind !== "Number") return true;
  if (role === "occ_mode" && point.kind !== "Number") return true;
  return false;
}

export function displayName(point) {
  const tags = tagsOf(point).filter((t) => !GENERIC.has(t) && t !== "sensor");
  if (tags.length) return tags.join(" ");
  return point.dis || point.column || point.role || "point";
}

import { NOT_ASSESSED_LABEL } from "./role-units.js";

export function unitLabel(point) {
  if (point?.unit_assessment && point.unit_assessment !== "assessed") {
    return NOT_ASSESSED_LABEL;
  }
  const declared = point?.declared_unit || point?.unit;
  if (declared) return declared;
  return point?.unit ?? "";
}

export function normalizeTags(rawTags, role) {
  const tags = Array.isArray(rawTags) ? [...rawTags] : [];
  if (!tags.includes("point")) tags.push("point");
  if (role.includes("web") || role === "web_oa_t") {
    if (!tags.includes("weather")) tags.push("weather");
  }
  return tags;
}
