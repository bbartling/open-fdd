const rawOpenClawUiUrl =
  import.meta.env.VITE_OPENFDDCLAW_UI_URL
  ?? import.meta.env.VITE_OPENCLAW_UI_URL
  ?? "http://127.0.0.1:18789/";

export const openClawUiUrl = rawOpenClawUiUrl.trim().replace(/\/+$/, "");

