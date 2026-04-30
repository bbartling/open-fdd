const defaultOpenClawUiUrl = "http://127.0.0.1:18789/";
const openClawUiCandidates = [
  import.meta.env.VITE_OPENFDDCLAW_UI_URL,
  import.meta.env.VITE_OPENCLAW_UI_URL,
];
const rawOpenClawUiUrl =
  openClawUiCandidates
    .map((candidate) => String(candidate ?? "").trim())
    .find((candidate) => candidate.length > 0)
  ?? defaultOpenClawUiUrl;

export const openClawUiUrl = rawOpenClawUiUrl.trim().replace(/\/+$/, "");

