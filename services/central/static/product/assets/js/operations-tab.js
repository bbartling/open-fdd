import { apiFetch } from "./api.js";
import { readToken } from "./session.js";
import { mountChart, disposeChart } from "./chart-kit.js";
import { MV_DEMO_SEED } from "./mv-demo-seed.js";
import { mvChartOption } from "./mv-charts.js";

function setMsg(el, text, isErr) {
  if (!el) return;
  if (!text) {
    el.textContent = "";
    el.hidden = true;
    el.classList.remove("ops-err");
    return;
  }
  el.textContent = text;
  el.hidden = false;
  el.classList.toggle("ops-err", Boolean(isErr));
}

function row(label, value) {
  const tr = document.createElement("tr");
  const th = document.createElement("th");
  th.textContent = label;
  const td = document.createElement("td");
  td.textContent = value;
  tr.append(th, td);
  return tr;
}

async function uploadPackage(file) {
  const token = readToken();
  if (!token) throw new Error("Sign in required");
  const form = new FormData();
  form.append("file", file, file.name);
  const headers = new Headers({ Accept: "application/json", Authorization: `Bearer ${token}` });
  const response = await fetch("/api/csv/import/package", { method: "POST", headers, body: form });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || payload.message || response.statusText);
  }
  if (!payload.ok) {
    throw new Error(payload.error || "Package import rejected");
  }
  return payload;
}

async function downloadBlob(path, filename) {
  const token = readToken();
  const headers = new Headers({ Accept: "application/zip" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function exportSiteCsvZip(buildingId) {
  const jobBody = await apiFetch("/api/jobs", {
    method: "POST",
    body: JSON.stringify({
      job_name: `static-ui-export-${Date.now()}`,
      building_id: buildingId,
    }),
  });
  const jobId = jobBody?.job?.job_id ?? jobBody?.job?.id;
  if (!jobId) throw new Error("Job create did not return job_id");
  const exportBody = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/exports`, {
    method: "POST",
    body: JSON.stringify({ building_id: buildingId, kind: "csv" }),
  });
  const exp = exportBody?.export;
  if (!exp?.download_url) throw new Error("Export missing download_url");
  await downloadBlob(exp.download_url, exp.filename || "site_history.zip");
}

async function runMvDemo(root) {
  const msg = root.querySelector("#demoMvMsg");
  const host = root.querySelector("#demoMvChart");
  setMsg(msg, "Running synthetic demo…", false);
  try {
    const envelope = await apiFetch("/api/analytics/mv", {
      method: "POST",
      body: JSON.stringify({
        query_version: "mv-change-point-v1",
        series: { ...MV_DEMO_SEED },
      }),
    });
    disposeChart(host);
    const option = mvChartOption(envelope);
    if (option) mountChart(host, option);
    const summary = root.querySelector("#demoMvSummary");
    if (summary) {
      summary.replaceChildren();
      const savings = envelope?.savings;
      if (savings && typeof savings === "object") {
        for (const [key, val] of Object.entries(savings)) {
          summary.append(row(key, String(val)));
        }
      } else {
        summary.append(row("status", envelope?.ok === false ? "failed" : "ok"));
      }
    }
    setMsg(msg, "", false);
  } catch (err) {
    disposeChart(host);
    setMsg(msg, err.message || String(err), true);
  }
}

async function refreshCsvSection(root, buildingId) {
  const tbody = root.querySelector("#csvBuildingsBody");
  const exportBtn = root.querySelector("#csvExportBtn");
  if (exportBtn) {
    exportBtn.disabled = !buildingId;
  }
  if (!tbody) return;
  tbody.replaceChildren();
  try {
    const body = await apiFetch("/api/csv/import/package/buildings");
    const ids = body?.building_ids ?? body?.buildings ?? [];
    const list = Array.isArray(ids) ? ids : [];
    if (!list.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 2;
      td.textContent = "No package sites loaded.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const id of list) {
      const tr = document.createElement("tr");
      const tdId = document.createElement("td");
      tdId.textContent = String(id);
      const tdAct = document.createElement("td");
      if (id === buildingId) {
        tdAct.textContent = "active session";
      } else {
        const link = document.createElement("a");
        link.href = `/app/?site=${encodeURIComponent(String(id))}&tab=ops`;
        link.textContent = "Open";
        tdAct.appendChild(link);
      }
      tr.append(tdId, tdAct);
      tbody.appendChild(tr);
    }
  } catch (err) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 2;
    td.textContent = err.message || String(err);
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

async function refreshAdminSection(root) {
  const panel = root.querySelector("#adminPanel");
  const denied = root.querySelector("#adminDenied");
  if (!panel || !denied) return;
  try {
    const me = await apiFetch("/api/auth/me");
    if (!me?.hub_admin) {
      panel.hidden = true;
      denied.hidden = false;
      return;
    }
    denied.hidden = true;
    panel.hidden = false;
    const usersBody = root.querySelector("#adminUsersBody");
    const tenantsBody = root.querySelector("#adminTenantsBody");
    const limitsBody = root.querySelector("#adminLimitsBody");
    const [users, tenants, limits] = await Promise.all([
      apiFetch("/api/admin/users").then((b) => b.users ?? []),
      apiFetch("/api/admin/tenants").then((b) => b.tenants ?? []),
      apiFetch("/api/admin/historian-limits").then((b) => b.limits ?? null),
    ]);
    if (usersBody) {
      usersBody.replaceChildren();
      for (const u of users) {
        const tr = document.createElement("tr");
        const name = document.createElement("td");
        name.textContent = u.username ?? "";
        const role = document.createElement("td");
        role.textContent = u.role ?? "";
        const tenantsCell = document.createElement("td");
        tenantsCell.textContent = (u.tenant_ids ?? []).join(", ") || "—";
        tr.append(name, role, tenantsCell);
        usersBody.appendChild(tr);
      }
    }
    if (tenantsBody) {
      tenantsBody.replaceChildren();
      for (const t of tenants) {
        const tr = document.createElement("tr");
        const id = document.createElement("td");
        id.textContent = t.id ?? "";
        const name = document.createElement("td");
        name.textContent = t.name ?? "";
        tr.append(id, name);
        tenantsBody.appendChild(tr);
      }
    }
    if (limitsBody && limits) {
      limitsBody.replaceChildren();
      limitsBody.append(
        row("retain_days", String(limits.retain_days ?? "—")),
        row("size_gib", String(limits.size_gib ?? "—")),
      );
    }
  } catch (err) {
    panel.hidden = true;
    denied.hidden = false;
    denied.textContent = err.message || "Admin APIs unavailable.";
  }
}

export function bindOperationsTab(root) {
  root.querySelector("#csvUploadForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    void (async () => {
      const msg = root.querySelector("#csvUploadMsg");
      const out = root.querySelector("#csvImportResult");
      const input = root.querySelector("#csvPackageFile");
      const file = input?.files?.[0];
      if (!file) {
        setMsg(msg, "Choose a package zip first.", true);
        return;
      }
      setMsg(msg, "Uploading…", false);
      if (out) out.textContent = "";
      try {
        const body = await uploadPackage(file);
        if (out) out.textContent = JSON.stringify(body, null, 2);
        setMsg(msg, body.building_id ? `Imported ${body.building_id}` : "Import OK", false);
        if (body.building_id) {
          const url = new URL(location.href);
          url.searchParams.set("site", body.building_id);
          url.searchParams.set("tab", "ops");
          location.assign(url.pathname + url.search);
        }
      } catch (err) {
        setMsg(msg, err.message || String(err), true);
      }
    })();
  });
  root.querySelector("#csvExportBtn")?.addEventListener("click", () => {
    void (async () => {
      const msg = root.querySelector("#csvExportMsg");
      const buildingId = root.dataset.buildingId || "";
      if (!buildingId) {
        setMsg(msg, "Select a site in the header first.", true);
        return;
      }
      setMsg(msg, "Building CSV zip export…", false);
      try {
        await exportSiteCsvZip(buildingId);
        setMsg(msg, "Download started.", false);
      } catch (err) {
        setMsg(msg, err.message || String(err), true);
      }
    })();
  });
  root.querySelector("#demoMvRun")?.addEventListener("click", () => {
    void runMvDemo(root);
  });
}

export async function refreshOperationsTab(buildingId) {
  const root = document.getElementById("tab-ops");
  if (!root) return;
  root.dataset.buildingId = buildingId || "";
  const siteLine = root.querySelector("#csvSessionSite");
  if (siteLine) {
    siteLine.textContent = buildingId || "— (header site picker)";
  }
  await Promise.all([
    refreshCsvSection(root, buildingId),
    refreshAdminSection(root),
  ]);
}

