import { apiFetch } from "./api.js";

/**
 * Populate a site <select> from the tenant-scoped building list.
 * Rejects `?site=` values outside the authorized list (does not add a foreign option).
 *
 * @returns {Promise<{ authorized: string[], queryRejected: string|null, selected: string }>}
 */
export async function populateSitePicker(selectEl, { querySite = null } = {}) {
  if (!selectEl) return { authorized: [], queryRejected: null, selected: "" };
  selectEl.replaceChildren();
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
    /* fall through — authorized list may stay empty */
  }

  const fromQuery = (querySite ?? new URLSearchParams(location.search).get("site") ?? "").trim();
  let queryRejected = null;
  if (fromQuery) {
    if (ids.has(fromQuery)) {
      selectEl.value = fromQuery;
    } else {
      queryRejected = fromQuery;
    }
  }

  if (ids.size === 0 && !fromQuery) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(no sites — configure providers or import CSV)";
    selectEl.appendChild(opt);
  }

  return {
    authorized: [...ids],
    queryRejected,
    selected: selectEl.value || "",
  };
}

export function isAuthorizedSite(siteId, authorized) {
  const id = (siteId ?? "").trim();
  if (!id) return false;
  return authorized.includes(id);
}
