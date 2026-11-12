// Units for Open-FDD: FDD and analytics math run in SI only; NF points arrive in whatever
// unit the site uses (often US customary); the UI shows the user's display system.
//
//   ingest  : ofddUnits.toSI(value, unit)        → { value, unit: SI unit, quantity } (or null if unknown)
//   display : ofddUnits.fromSI(value, siUnit, sys) → { value, unit } in "imperial" | "si"
//   delta   : ofddUnits.deltaFromSI(d, siUnit, sys) — temperature differences (no 32 offset)
//
// Canonical SI per quantity (same as sql/analytics/SI_STORAGE.md):
//   temperature °C · pressure Pa · air/water flow L/s · power kW · energy kWh · percent % (0–100)
// Classic script (browser global `ofddUnits`) and CommonJS (FDD hook) from one file.
(function (root) {
  const norm = (u) => String(u || "").trim().toLowerCase().replace(/[\s_]/g, "").replace("₂", "2").replace("º", "°");

  // unit → [quantity, SI unit, toSI(x)]
  const TABLE = Object.create(null);
  const add = (names, quantity, si, f) => { for (const n of names) TABLE[norm(n)] = [quantity, si, f]; };
  const id = (x) => x;
  // BEGIN GENERATED unit factors (open_fdd/data/unit_factors.json; python scripts/nf/build_unit_factors.py)
  const F = {
    pa_per_in_wc: 249.0889,
    pa_per_psi: 6894.757,
    lps_per_cfm: 0.4719474,
    lps_per_gpm: 0.0630902,
    kw_per_btuh: 0.00029307107,
    kw_per_ton: 3.5168525,
    kw_per_hp: 0.7456999,
    kwh_per_kbtu: 0.29307107,
    kwh_per_mmbtu: 293.07107,
    kwh_per_therm: 29.307107,
  };
  // END GENERATED unit factors
  add(["°C", "degC", "C", "celsius", "deg_c", "degrees-celsius"], "temperature", "°C", id);
  add(["°F", "degF", "F", "fahrenheit", "deg_f", "degrees-fahrenheit"], "temperature", "°C", (x) => (x - 32) * 5 / 9);
  add(["K", "kelvin"], "temperature", "°C", (x) => x - 273.15);
  add(["Pa", "pascal", "pascals"], "pressure", "Pa", id);
  add(["kPa", "kilopascals"], "pressure", "Pa", (x) => x * 1000);
  add(["inH2O", "inH20", "inWC", "in wc", "in. w.c.", "inH₂O", "\"wc", "in_h2o",
    "inches of water", "inches-of-water", "iwc"], "pressure", "Pa", (x) => x * F.pa_per_in_wc);
  add(["psi", "psig", "psid"], "pressure", "Pa", (x) => x * F.pa_per_psi);
  add(["bar"], "pressure", "Pa", (x) => x * 1e5);
  add(["L/s", "lps", "L/sec", "liters/second", "litres/second", "liters per second", "litres per second",
    "liters-per-second"], "flow", "L/s", id);
  add(["m³/s", "m3/s"], "flow", "L/s", (x) => x * 1000);
  add(["m³/h", "m3/h", "cmh"], "flow", "L/s", (x) => x / 3.6);
  add(["cfm", "ft³/min", "ft3/min", "cubic-feet-per-minute"], "flow", "L/s", (x) => x * F.lps_per_cfm);
  add(["gpm", "gal/min"], "flow", "L/s", (x) => x * F.lps_per_gpm);
  add(["kW"], "power", "kW", id);
  add(["W"], "power", "kW", (x) => x / 1000);
  add(["MW"], "power", "kW", (x) => x * 1000);
  add(["Btu/h", "btuh", "btu/hr"], "power", "kW", (x) => x * F.kw_per_btuh);
  add(["ton", "tons", "tonref", "tr"], "power", "kW", (x) => x * F.kw_per_ton);
  add(["hp"], "power", "kW", (x) => x * F.kw_per_hp);
  add(["kWh"], "energy", "kWh", id);
  add(["Wh"], "energy", "kWh", (x) => x / 1000);
  add(["MWh"], "energy", "kWh", (x) => x * 1000);
  add(["kBtu"], "energy", "kWh", (x) => x * F.kwh_per_kbtu);
  add(["MMBtu"], "energy", "kWh", (x) => x * F.kwh_per_mmbtu);
  add(["therm", "therms"], "energy", "kWh", (x) => x * F.kwh_per_therm);
  add(["%", "%RH", "percent", "pct", "percent-relative-humidity"], "percent", "%", id);
  add(["ppm"], "concentration", "ppm", id);

  /** Value in canonical SI, or null when the unit is unknown/empty (caller keeps it as-is). */
  function toSI(value, unit) {
    const row = TABLE[norm(unit)];
    if (!row || value == null || !Number.isFinite(Number(value))) return null;
    return { value: row[2](Number(value)), unit: row[1], quantity: row[0] };
  }

  const quantityOf = (unit) => (TABLE[norm(unit)] || [null])[0];
  const isSI = (unit) => { const r = TABLE[norm(unit)]; return !!r && norm(r[1]) === norm(unit); };

  // SI → display. Imperial = US customary as commonly shown on a BAS.
  const IMPERIAL = {
    "°C": ["°F", (x) => x * 9 / 5 + 32, (d) => d * 9 / 5],
    Pa: ["inH₂O", (x) => x / F.pa_per_in_wc, (d) => d / F.pa_per_in_wc],
    "L/s": ["cfm", (x) => x / F.lps_per_cfm, (d) => d / F.lps_per_cfm],
    kW: ["kW", (x) => x, (d) => d],
    kWh: ["kWh", (x) => x, (d) => d],
  };

  /** SI value → display system ("imperial" | "si"). Unknown SI units pass through. */
  function fromSI(value, siUnit, system) {
    if (value == null || !Number.isFinite(Number(value))) return { value: null, unit: siUnit || "" };
    const m = system === "imperial" && IMPERIAL[siUnit];
    return m ? { value: m[1](Number(value)), unit: m[0] } : { value: Number(value), unit: siUnit || "" };
  }

  /** Temperature (or other) *difference* SI → display (no offset). */
  function deltaFromSI(delta, siUnit, system) {
    const m = system === "imperial" && IMPERIAL[siUnit];
    return m ? { value: m[2](Number(delta)), unit: (siUnit === "°C" ? "Δ°F" : m[0]) } : { value: Number(delta), unit: siUnit === "°C" ? "Δ°C" : siUnit };
  }

  /** Display system: user choice (localStorage "openfdd-units"), default imperial (US sites). */
  function displaySystem() {
    try {
      const v = root.localStorage && root.localStorage.getItem("openfdd-units");
      return v === "si" ? "si" : "imperial";
    } catch (e) {
      return "imperial";
    }
  }

  /** Point value → display: SI-convert by its own unit, then into the display system. */
  function display(value, unit, system) {
    const si = toSI(value, unit);
    return si ? fromSI(si.value, si.unit, system || displaySystem()) : { value: value == null ? null : Number(value), unit: unit || "" };
  }

  const api = { toSI, fromSI, deltaFromSI, display, displaySystem, quantityOf, isSI, normUnit: norm };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ofddUnits = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
