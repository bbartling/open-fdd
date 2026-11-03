/** Plot titles for FDD charts (rule id + equipment). */

export function ruleLabelPlotTitle(ruleId, equipmentId, description) {
  const id = String(ruleId ?? "").trim();
  const desc = description?.trim() || id;
  const base = !id || desc === id ? desc : `${id} — ${desc}`;
  const eq = String(equipmentId ?? "").trim();
  return eq ? `${base} · ${eq}` : base;
}
