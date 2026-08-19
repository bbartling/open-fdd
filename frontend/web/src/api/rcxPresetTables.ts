import type { AnalyticsEnvelope } from "./analyticsApi";
import { mechFigure } from "./centralOverview";
import {
  isWeatherEquipmentId,
  isZoneTerminalEquipment,
} from "../lib/overviewMetrics";

export interface RcxPresetTable {
  id: string;
  label: string;
  rows: Array<Record<string, unknown>>;
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const PLANT_FOR: Record<string, string> = {
  ahu_motor_weekly: "air",
  boiler_motor_weekly: "boiler",
  chiller_motor_weekly: "chiller",
};

/** Tabular data that lived on Overview — shown under the matching RCx preset plot. */
export function rcxPresetTables(
  presetId: string,
  env: AnalyticsEnvelope,
): RcxPresetTable[] {
  const rows = env.rows ?? [];
  const equipment = env.equipment ?? [];
  const allRows = rows.length ? rows : equipment;

  if (presetId in PLANT_FOR) {
    const plantGroup = PLANT_FOR[presetId];
    const weekly = rows.filter(
      (r) =>
        (r.kind === "weekly_equipment" || r.kind === "weekly_plant") &&
        String(r.plant_group ?? "") === plantGroup &&
        !isZoneTerminalEquipment(r),
    );
    const out: RcxPresetTable[] = [];
    if (weekly.length) {
      out.push({
        id: "weekly-motor-hours",
        label: "Weekly motor hours",
        rows: weekly.slice(0, 200),
      });
    }
    const totals = allRows.filter(
      (r) =>
        r.kind !== "weekly_plant" &&
        r.kind !== "weekly_equipment" &&
        !isWeatherEquipmentId(String(r.equipment_id ?? "")) &&
        !isZoneTerminalEquipment(r),
    );
    if (totals.length) {
      out.push({
        id: "motor-equipment-totals",
        label: "Equipment run hours",
        rows: totals.slice(0, 200),
      });
    }
    return out;
  }

  if (presetId === "mech_cooling_oat_bins") {
    const { bins } = mechFigure(allRows);
    const out: RcxPresetTable[] = [];
    if (bins.length) {
      out.push({
        id: "mech-oat-bins",
        label: "Mechanical cooling OAT bins",
        rows: bins.slice(0, 80),
      });
    }
    const coverage = allRows
      .filter((r) => r.kind !== "oat_bin" && num(r.history_rows) != null)
      .slice(0, 200);
    if (coverage.length) {
      out.push({
        id: "mech-coverage",
        label: "Cooling coverage",
        rows: coverage,
      });
    }
    return out;
  }

  if (
    presetId === "economizer_delta" ||
    presetId === "economizer_mat_resid" ||
    presetId === "economizer_temps_overlay"
  ) {
    if (allRows.length) {
      return [
        {
          id: "econ-diagnostics",
          label: "Economizer diagnostics",
          rows: allRows.slice(0, 200),
        },
      ];
    }
    return [];
  }

  if (presetId === "bas_vs_web_oat") {
    const hist = rows.filter(
      (r) => r.kind === "delta_hist" || num(r.count) != null,
    );
    if (hist.length) {
      return [
        {
          id: "bas-oat-hist",
          label: "BAS − web OAT deviation histogram",
          rows: hist.slice(0, 80),
        },
      ];
    }
    return [];
  }

  return [];
}
