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
  const TABLE = {};
  const add = (names, quantity, si, f) => { for (const n of names) TABLE[norm(n)] = [quantity, si, f]; };
  const id = (x) => x;
  add(["°C", "degC", "C", "celsius", "deg_c"], "temperature", "°C", id);
  add(["°F", "degF", "F", "fahrenheit", "deg_f"], "temperature", "°C", (x) => (x - 32) * 5 / 9);
  add(["K", "kelvin"], "temperature", "°C", (x) => x - 273.15);
  add(["Pa", "pascal"], "pressure", "Pa", id);
  add(["kPa"], "pressure", "Pa", (x) => x * 1000);
  add(["inH2O", "inWC", "in wc", "in. w.c.", "inH₂O", "\"wc", "in_h2o"], "pressure", "Pa", (x) => x * 249.0889);
  add(["psi", "psig", "psid"], "pressure", "Pa", (x) => x * 6894.757);
  add(["bar"], "pressure", "Pa", (x) => x * 1e5);
  add(["L/s", "l/s", "lps"], "flow", "L/s", id);
  add(["m³/s", "m3/s"], "flow", "L/s", (x) => x * 1000);
  add(["m³/h", "m3/h", "cmh"], "flow", "L/s", (x) => x / 3.6);
  add(["cfm", "ft³/min", "ft3/min"], "flow", "L/s", (x) => x * 0.4719474);
  add(["gpm", "gal/min"], "flow", "L/s", (x) => x * 0.0630902);
  add(["kW"], "power", "kW", id);
  add(["W"], "power", "kW", (x) => x / 1000);
  add(["MW"], "power", "kW", (x) => x * 1000);
  add(["Btu/h", "btuh", "btu/hr"], "power", "kW", (x) => x * 0.00029307107);
  add(["ton", "tons", "tonref", "tr"], "power", "kW", (x) => x * 3.5168525);
  add(["hp"], "power", "kW", (x) => x * 0.7456999);
  add(["kWh"], "energy", "kWh", id);
  add(["Wh"], "energy", "kWh", (x) => x / 1000);
  add(["MWh"], "energy", "kWh", (x) => x * 1000);
  add(["kBtu"], "energy", "kWh", (x) => x * 0.29307107);
  add(["MMBtu"], "energy", "kWh", (x) => x * 293.07107);
  add(["therm", "therms"], "energy", "kWh", (x) => x * 29.307107);
  add(["%", "%RH", "percent", "pct"], "percent", "%", id);
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
    Pa: ["inH₂O", (x) => x / 249.0889, (d) => d / 249.0889],
    "L/s": ["cfm", (x) => x / 0.4719474, (d) => d / 0.4719474],
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
