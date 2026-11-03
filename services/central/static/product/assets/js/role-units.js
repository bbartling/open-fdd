/** Display-only unit helpers (historian stays SI). Imperial toggle deferred (Bench Viz gap). */

const C_TO_F = (c) => (c * 9) / 5 + 32;

export function displayTempC(valueC, unitSystem = "metric") {
  const n = Number(valueC);
  if (!Number.isFinite(n)) return null;
  if (unitSystem === "imperial") return C_TO_F(n);
  return n;
}

/** Temperature deltas/rates: scale only, no +32 offset. */
export function displayDeltaC(valueC, unitSystem = "metric") {
  const n = Number(valueC);
  if (!Number.isFinite(n)) return null;
  if (unitSystem === "imperial") return (n * 9) / 5;
  return n;
}

export function tempAxisLabel(unitSystem = "metric") {
  return unitSystem === "imperial" ? "°F" : "°C";
}
