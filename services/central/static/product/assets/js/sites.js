import { apiFetch } from "./api.js";

const SITE_BUILDINGS_PATH = "/api/sites/buildings";

/**
 * Load tenant-scoped building ids into a <select> (provider sites + CSV/historian).
 * Ensures `?site=` is present as an option before selection when the caller may see it.
 */
export async function populateSitePicker(selectEl, { querySite = null } = {}) {
  if (!selectEl) return [];
  selectEl.innerHTML = "";
  let buildings = [];
  try {
    const body = await apiFetch(SITE_BUILDINGS_PATH);
    buildings = body?.buildings ?? [];
  } catch {
    buildings = [];
  }

  const ids = [];
  for (const row of buildings) {
    const id = (row?.building_id ?? row?.id ?? row ?? "").toString().trim();
    if (!id || ids.includes(id)) continue;
    ids.push(id);
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    selectEl.appendChild(opt);
  }

  const fromQuery = (querySite ?? new URLSearchParams(location.search).get("site") ?? "").trim();
  if (fromQuery && !ids.includes(fromQuery)) {
    const opt = document.createElement("option");
    opt.value = fromQuery;
    opt.textContent = fromQuery;
    selectEl.appendChild(opt);
    ids.push(fromQuery);
  }

  if (ids.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no sites — use ?site= or CSV import)";
    selectEl.appendChild(opt);
  } else if (fromQuery && ids.includes(fromQuery)) {
    selectEl.value = fromQuery;
  } else if (ids.length === 1) {
    selectEl.value = ids[0];
  }

  return ids;
}
