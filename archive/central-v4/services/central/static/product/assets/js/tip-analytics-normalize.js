/** Port of archive/product-ui/react-spa-v4/src/api/tipAnalyticsNormalize.ts */

export const ECONOMIZER_DT_MIN_C = 50 / 9;

function num(v) {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function str(v) {
  return v == null ? "" : String(v);
}

export function tipOatBinLo(label) {
  const s = String(label).trim();
  if (s.startsWith("<")) {
    const n = Number(s.slice(1));
    return Number.isFinite(n) ? n - 0.1 : 0;
  }
  if (s.startsWith(">=")) {
    const n = Number(s.slice(2));
    return Number.isFinite(n) ? n : 90;
  }
  const m = s.match(/^(-?\d+(?:\.\d+)?)/);
  return m ? Number(m[1]) : 0;
}

function plantGroupForOverview(raw) {
  const g = String(raw).trim().toLowerCase();
  if (g === "ahu" || g === "air" || g === "rtu" || g === "uv") return "air";
  if (g === "boiler" || g === "hw") return "boiler";
  if (g === "chiller" || g === "chw") return "chiller";
  return g || "air";
}

function cloneEnv(env) {
  return {
    ...env,
    rows: Array.isArray(env?.rows) ? [...env.rows] : [],
    equipment: Array.isArray(env?.equipment) ? [...env.equipment] : [],
    points: Array.isArray(env?.points) ? [...env.points] : [],
    skipped: Array.isArray(env?.skipped) ? [...env.skipped] : [],
    warnings: Array.isArray(env?.warnings) ? [...env.warnings] : [],
  };
}

export function normalizeTipRuntimeRows(rows) {
  return (rows || []).map((r) => {
    const equipment_id = str(r.equipment_id);
    const week_label = str(r.week_label);
    const run = num(r.run_hours) ?? num(r.runtime_hours);
    const kindRaw = str(r.kind);
    const looksWeekly =
      Boolean(week_label) &&
      (kindRaw === "" ||
        kindRaw === "motor" ||
        kindRaw === "weekly_equipment" ||
        kindRaw === "weekly_plant");
    const plant_group = plantGroupForOverview(str(r.plant_group));
    if (looksWeekly && kindRaw !== "weekly_plant") {
      return {
        ...r,
        kind: "weekly_equipment",
        plant_group,
        equipment_id,
        week_label,
        run_hours: run,
        runtime_hours: run,
        label: str(r.label) || `${equipment_id} · fan-status`,
      };
    }
    return {
      ...r,
      equipment_id,
      plant_group: str(r.plant_group) ? plant_group : r.plant_group,
      run_hours: run ?? r.run_hours,
      runtime_hours: run ?? r.runtime_hours,
    };
  });
}

export function normalizeTipMechRows(rows) {
  return (rows || []).map((r) => {
    const oat_bin = str(r.oat_bin || r.bin_label);
    const kindRaw = str(r.kind);
    const isBin = kindRaw === "oat_bin" || Boolean(oat_bin);
    if (!isBin) return r;
    const hours = num(r.hours) ?? num(r.run_hours);
    const bin_lo_f = num(r.bin_lo_f) ?? (oat_bin ? tipOatBinLo(oat_bin) : null);
    return {
      ...r,
      kind: "oat_bin",
      oat_bin: oat_bin || r.oat_bin,
      bin_label: str(r.bin_label) || oat_bin,
      hours: hours ?? r.hours,
      run_hours: hours ?? r.run_hours,
      bin_lo_f: bin_lo_f ?? r.bin_lo_f,
      series_kind: r.series_kind ?? "individual_device",
    };
  });
}

export function explicitFanOn(v) {
  if (v === true || v === 1) return true;
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    return s === "true" || s === "1";
  }
  return false;
}

function mixingResidualF(oat, rat, mat, damperPct) {
  if (oat == null || rat == null || mat == null || damperPct == null) return null;
  return mat - (rat + (damperPct / 100) * (oat - rat));
}

function pushWarning(env, message) {
  if (!env.warnings.includes(message)) env.warnings.push(message);
}

function rowDeltaOrC(r) {
  const direct = num(r.delta_or_c);
  if (direct != null) return direct;
  const oat = num(r.oa_t);
  const rat = num(r.rat);
  return oat != null && rat != null ? oat - rat : null;
}

function economizerUnqualifiedReason(rows, dtMinC) {
  if (!rows.length) {
    return `No economizer rows. Fan-on proof, |OAT−RAT| ≥ ${dtMinC}°C, and a measured MAT are required.`;
  }
  const parts = [];
  if (!rows.some((r) => explicitFanOn(r.fan_on))) {
    parts.push("fan status is not proven on");
  }
  const deltas = rows.map((r) => rowDeltaOrC(r)).filter((d) => d != null);
  if (deltas.length > 0 && deltas.every((d) => Math.abs(d) < dtMinC)) {
    parts.push(`|OAT−RAT| is below ${dtMinC}°C`);
  }
  if (!rows.some((r) => num(r.mat) != null)) {
    parts.push("MAT is missing");
  }
  if (!parts.length) {
    parts.push(
      "fan-on, minimum |OAT−RAT|, and measured MAT are not all present on the same row",
    );
  }
  return `Economizer rows are not qualified: ${parts.join("; ")}.`;
}

export function normalizeTipEconomizerPoints(rows, existingPoints, dtMinC = ECONOMIZER_DT_MIN_C) {
  if (existingPoints?.length) return existingPoints;
  return (rows || [])
    .map((r) => {
      const oa_t = num(r.oa_t);
      const rat = num(r.rat);
      const mat = num(r.mat);
      const damper_fb_pct =
        num(r.damper_fb_pct) ?? num(r.oa_damper_pct) ?? num(r.damper_pct);
      const delta_or_c =
        num(r.delta_or_c) ?? (oa_t != null && rat != null ? oa_t - rat : null);
      const delta_mr_c =
        num(r.delta_mr_c) ?? (mat != null && rat != null ? mat - rat : null);
      const fan_on = explicitFanOn(r.fan_on);
      const identifiable =
        fan_on &&
        mat != null &&
        delta_or_c != null &&
        delta_mr_c != null &&
        Math.abs(delta_or_c) >= dtMinC;
      const timestamp_utc = str(r.timestamp_utc) || str(r.ts) || str(r.time_utc);
      return {
        ...r,
        timestamp_utc,
        equipment_id: str(r.equipment_id) || "AHU",
        oa_t,
        rat,
        mat,
        sat: num(r.sat),
        damper_fb_pct,
        oa_damper_pct: damper_fb_pct,
        delta_or_c,
        delta_mr_c,
        mat_resid_c:
          num(r.mat_resid_c) ?? mixingResidualF(oa_t, rat, mat, damper_fb_pct),
        identifiable,
        fan_on,
      };
    })
    .filter((p) => p.timestamp_utc || p.delta_or_c != null);
}

export function normalizeTipBasPoints(rows, existingPoints) {
  if (existingPoints?.length) return existingPoints;
  return (rows || [])
    .filter((r) => str(r.kind) !== "delta_hist")
    .map((r) => ({
      ...r,
      timestamp_utc: str(r.timestamp_utc) || str(r.ts) || str(r.time_utc),
      equipment_id: str(r.equipment_id) || "site",
      bas_oat_c: num(r.bas_oat_c) ?? num(r.bas_oa_t),
      web_oat_c: num(r.web_oat_c) ?? num(r.web_oa_t),
      delta_c: num(r.delta_c),
    }))
    .filter((p) => p.timestamp_utc && (p.bas_oat_c != null || p.web_oat_c != null));
}

export function normalizeTipOverviewEnvelope(query, env, opts) {
  const out = cloneEnv(env || {});
  if (query === "runtime") {
    out.rows = normalizeTipRuntimeRows(out.rows);
    if (!out.equipment.length) {
      out.equipment = out.rows.filter(
        (r) => str(r.kind) !== "weekly_equipment" && str(r.kind) !== "weekly_plant",
      );
    }
    if (!out.rows.some((r) => str(r.kind) === "weekly_equipment")) {
      pushWarning(out, "No motor weekly runtime rows for this site and window.");
    }
    return out;
  }
  if (query === "mechanical-cooling") {
    out.rows = normalizeTipMechRows(out.rows);
    if (!out.rows.some((r) => str(r.kind) === "oat_bin")) {
      pushWarning(
        out,
        "No mechanical-cooling outdoor-air bins. Compressor or chiller status with outdoor air is required.",
      );
    }
    return out;
  }
  if (query === "economizer") {
    const dtMinC = opts?.dtMinC ?? ECONOMIZER_DT_MIN_C;
    out.points = normalizeTipEconomizerPoints(out.rows, out.points, dtMinC);
    const qualified = out.points.some(
      (p) => p.identifiable === true || p.identifiable === "true",
    );
    if (!qualified) {
      pushWarning(out, economizerUnqualifiedReason(out.rows, dtMinC));
    }
    return out;
  }
  out.points = normalizeTipBasPoints(out.rows, out.points);
  if (!out.points.length) {
    pushWarning(
      out,
      "No coincident BAS and web outdoor-air samples for this site and window.",
    );
  }
  return out;
}

export function isIdentifiablePoint(p) {
  return p?.identifiable === true || p?.identifiable === "true";
}
