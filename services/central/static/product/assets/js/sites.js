import { apiFetch } from "./api.js";

/**
 * Populate a site <select> from the tenant-scoped building list.
 * Ensures `?site=` has a matching <option> before selection.
 */
export async function populateSitePicker(selectEl, { querySite = null } = {}) {
  if (!selectEl) return [];
  selectEl.innerHTML = "";
  const ids = new Set();

  const addOption = (id, label = id) => {
    const trimmed = (id ?? "").trim();
    if (!trimmed || ids.has(trimmed)) return;
    ids.add(trimmed);
    const opt = document.createElement("option");
    opt.value = trimmed;
    opt.textContent = label || trimmed;
    selectEl.appendChild(opt);
  };

  try {
    const body = await apiFetch("/api/sites/buildings");
    const rows = body?.buildings ?? [];
    if (Array.isArray(rows)) {
      for (const row of rows) {
        if (typeof row === "string") {
          addOption(row);
          continue;
        }
        const id = row?.building_id ?? row?.id ?? "";
        addOption(id);
      }
    }
  } catch {
    /* fall through — querySite may still apply */
  }

  const fromQuery =
    (querySite ?? new URLSearchParams(location.search).get("site") ?? "").trim();
  if (fromQuery) {
    addOption(fromQuery);
    selectEl.value = fromQuery;
  }

  if (ids.size === 0 && !fromQuery) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no sites — configure providers or import CSV)";
    selectEl.appendChild(opt);
  }

  return [...ids];
}
