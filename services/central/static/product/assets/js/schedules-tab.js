import { apiFetch } from "./api.js";

const POLL_OPTIONS = [
  { secs: 900, label: "15 min" },
  { secs: 1800, label: "30 min" },
  { secs: 3600, label: "1 h" },
  { secs: 7200, label: "2 h" },
];

const AFDD_INTERVALS = [
  { minutes: 60, label: "Every 1 hour" },
  { minutes: 180, label: "Every 3 hours" },
  { minutes: 360, label: "Every 6 hours" },
  { minutes: 720, label: "Every 12 hours" },
  { minutes: 1440, label: "Every 24 hours" },
];

function fmtTime(value) {
  if (!value) return "—";
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : String(value);
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

function setMsg(el, text, isErr) {
  if (!el) return;
  if (!text) {
    el.textContent = "";
    el.hidden = true;
    el.classList.remove("sched-err");
    return;
  }
  el.textContent = text;
  el.hidden = false;
  el.classList.toggle("sched-err", Boolean(isErr));
}

export function bindSchedulesTab(root) {
  initSchedulesTabPickers(root);
  const modelForm = root.querySelector("#modelSyncForm");
  const historyForm = root.querySelector("#historyScheduleForm");
  const afddForm = root.querySelector("#afddScheduleForm");
  modelForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    void saveModelSync(root);
  });
  historyForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    void saveHistorySchedule(root);
  });
  afddForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    void saveAfddSchedule(root);
  });
  root.querySelector("#afddRunNowBtn")?.addEventListener("click", () => {
    void runAfddNow(root);
  });
}

export async function refreshSchedulesTab(buildingId) {
  const root = document.getElementById("tab-schedules");
  if (!root || !buildingId) return;
  root.dataset.buildingId = buildingId;
  setMsg(root.querySelector("#schedLoadMsg"), "Loading schedules…", false);
  try {
    const [summary, coverage, afdd] = await Promise.all([
      apiFetch(`/api/schedules/status?building_id=${encodeURIComponent(buildingId)}`),
      apiFetch(
        `/api/ingest/gaps?view=status&site_id=${encodeURIComponent(buildingId)}`,
      ).catch(() => null),
      apiFetch("/api/afdd/scheduler/status").catch(() => null),
    ]);
    renderSchedules(root, buildingId, summary, coverage, afdd);
    setMsg(root.querySelector("#schedLoadMsg"), "", false);
  } catch (err) {
    setMsg(root.querySelector("#schedLoadMsg"), err.message || String(err), true);
  }
}

function renderSchedules(root, buildingId, summary, coverage, afdd) {
  const providerConfigured = summary?.provider_configured === true;
  root.querySelectorAll(".sched-provider-only").forEach((el) => {
    el.hidden = !providerConfigured;
  });
  const editable = summary?.editable === true && providerConfigured;
  root.querySelectorAll(".sched-editable").forEach((el) => {
    el.disabled = !editable;
  });
  const modelBody = root.querySelector("#modelSyncStatus");
  const historyBody = root.querySelector("#historyScheduleStatus");
  const afddBody = root.querySelector("#afddScheduleStatus");
  if (modelBody) {
    modelBody.replaceChildren();
    const model = summary?.model_sync ?? {};
    modelBody.append(
      row("Poll interval", model.poll_secs ? `${model.poll_secs}s` : "—"),
      row("Last run", fmtTime(model.last_run)),
      row("Last error", model.last_error ? String(model.last_error) : "—"),
      row("Points ingested", model.ingested_points ?? "—"),
    );
    const pick = root.querySelector("#modelPollPick");
    if (pick && model.poll_secs) {
      pick.value = String(model.poll_secs);
    }
  }
  if (historyBody) {
    historyBody.replaceChildren();
    const hist = summary?.history ?? {};
    const provider =
      coverage?.providers?.find?.((p) => p) ?? coverage?.providers?.[0];
    const covStatus = provider?.status ?? {};
    historyBody.append(
      row("Mode", hist.schedule_mode ?? "—"),
      row("Timezone", hist.schedule_timezone ?? "—"),
      row("Coverage", coverage?.state ?? "—"),
      row("Next run", fmtTime(provider?.next_run)),
      row("Planned through", fmtTime(provider?.planned_through)),
      row("Verified through", fmtTime(covStatus.verified_through)),
      row("Blocking gap", covStatus.oldest_gap ? String(covStatus.oldest_gap) : "—"),
    );
    const modePick = root.querySelector("#historyModePick");
    const tzInput = root.querySelector("#historyTzInput");
    if (modePick && hist.schedule_mode) modePick.value = hist.schedule_mode;
    if (tzInput && hist.schedule_timezone) tzInput.value = hist.schedule_timezone;
  }
  if (afddBody) {
    afddBody.replaceChildren();
    const siteRow =
      afdd?.sites?.find?.((s) => s.building_id === buildingId) ??
      afdd?.sites?.[0];
    const cfg = afdd?.config ?? {};
    afddBody.append(
      row("Mode", cfg.mode ?? "—"),
      row("Next due", fmtTime(siteRow?.next_due_at_utc)),
      row("Analyzed through", fmtTime(siteRow?.checkpoint?.analyzed_through_utc)),
      row("Last cycle", siteRow?.last_cycle?.status ?? "—"),
      row("Last error", siteRow?.last_cycle?.error ? String(siteRow.last_cycle.error) : "—"),
    );
    const kindPick = root.querySelector("#afddKindPick");
    const intervalPick = root.querySelector("#afddIntervalPick");
    const lookbackPick = root.querySelector("#afddLookbackPick");
    if (kindPick) {
      kindPick.value = cfg.schedule_kind === "wall_clock" ? "wall_clock" : "interval";
    }
    if (intervalPick && cfg.interval_minutes) {
      intervalPick.value = String(cfg.interval_minutes);
    }
    if (lookbackPick && cfg.lookback_unit === "days") {
      lookbackPick.value = String(cfg.lookback_value ?? 1);
    }
  }
}

async function saveModelSync(root) {
  const buildingId = root.dataset.buildingId;
  const poll_secs = Number(root.querySelector("#modelPollPick")?.value);
  setMsg(root.querySelector("#modelSyncMsg"), "Saving…", false);
  try {
    await apiFetch("/api/schedules/model-sync", {
      method: "POST",
      body: JSON.stringify({ building_id: buildingId, poll_secs }),
    });
    setMsg(root.querySelector("#modelSyncMsg"), "Model sync schedule saved.", false);
    await refreshSchedulesTab(buildingId);
  } catch (err) {
    setMsg(root.querySelector("#modelSyncMsg"), err.message || String(err), true);
  }
}

async function saveHistorySchedule(root) {
  const buildingId = root.dataset.buildingId;
  const schedule_mode = root.querySelector("#historyModePick")?.value ?? "periodic";
  const schedule_timezone = root.querySelector("#historyTzInput")?.value?.trim();
  setMsg(root.querySelector("#historyScheduleMsg"), "Saving…", false);
  try {
    await apiFetch("/api/schedules/history", {
      method: "POST",
      body: JSON.stringify({
        building_id: buildingId,
        schedule_mode,
        schedule_timezone: schedule_mode === "daily" ? schedule_timezone : undefined,
      }),
    });
    setMsg(root.querySelector("#historyScheduleMsg"), "History schedule saved.", false);
    await refreshSchedulesTab(buildingId);
  } catch (err) {
    setMsg(root.querySelector("#historyScheduleMsg"), err.message || String(err), true);
  }
}

async function saveAfddSchedule(root) {
  const schedule_kind = root.querySelector("#afddKindPick")?.value ?? "interval";
  const interval_minutes = Number(root.querySelector("#afddIntervalPick")?.value ?? 60);
  const lookbackDays = Number(root.querySelector("#afddLookbackPick")?.value ?? 1);
  setMsg(root.querySelector("#afddScheduleMsg"), "Saving…", false);
  try {
    await apiFetch("/api/afdd/scheduler/config", {
      method: "POST",
      body: JSON.stringify({
        schedule_kind,
        interval_minutes: schedule_kind === "wall_clock" ? 1440 : interval_minutes,
        lookback_value: lookbackDays,
        lookback_unit: "days",
        wall_clock_hhmm: root.querySelector("#afddWallClock")?.value ?? "05:00",
        wall_clock_timezone: root.querySelector("#afddWallTz")?.value ?? "",
      }),
    });
    setMsg(root.querySelector("#afddScheduleMsg"), "AFDD schedule saved.", false);
    await refreshSchedulesTab(root.dataset.buildingId);
  } catch (err) {
    setMsg(root.querySelector("#afddScheduleMsg"), err.message || String(err), true);
  }
}

async function runAfddNow(root) {
  const buildingId = root.dataset.buildingId;
  setMsg(root.querySelector("#afddScheduleMsg"), "Running AFDD cycle…", false);
  try {
    await apiFetch("/api/afdd/scheduler/run-now", {
      method: "POST",
      body: JSON.stringify({ building_id: buildingId }),
    });
    setMsg(root.querySelector("#afddScheduleMsg"), "Run-now completed.", false);
    await refreshSchedulesTab(buildingId);
  } catch (err) {
    setMsg(root.querySelector("#afddScheduleMsg"), err.message || String(err), true);
  }
}

export function initSchedulesTabPickers(root) {
  const pollPick = root.querySelector("#modelPollPick");
  if (pollPick && !pollPick.options.length) {
    for (const opt of POLL_OPTIONS) {
      const el = document.createElement("option");
      el.value = String(opt.secs);
      el.textContent = opt.label;
      pollPick.appendChild(el);
    }
  }
  const intervalPick = root.querySelector("#afddIntervalPick");
  if (intervalPick && !intervalPick.options.length) {
    for (const opt of AFDD_INTERVALS) {
      const el = document.createElement("option");
      el.value = String(opt.minutes);
      el.textContent = opt.label;
      intervalPick.appendChild(el);
    }
  }
}
