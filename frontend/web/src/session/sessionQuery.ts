/**
 * Session/URL state translation for shareable query parameters.
 * Durable domain state stays on Rust APIs; URL holds shareable selection only.
 * Form drafts may use sessionStorage; never the sole home of job/mapping authority.
 */

export type SessionQuery = {
  section?: string;
  jobId?: string;
  equipment?: string;
  siteId?: string;
  wattlabPage?: string;
};

export const SESSION_KEYS = {
  section: "section",
  jobId: "job",
  equipment: "eq",
  siteId: "site",
  wattlabPage: "wl",
} as const;

export function parseSessionSearch(search: string): SessionQuery {
  const params = new URLSearchParams(
    search.startsWith("?") ? search.slice(1) : search,
  );
  const out: SessionQuery = {};
  const section = params.get(SESSION_KEYS.section);
  const jobId = params.get(SESSION_KEYS.jobId);
  const equipment = params.get(SESSION_KEYS.equipment);
  const siteId = params.get(SESSION_KEYS.siteId);
  const wattlabPage = params.get(SESSION_KEYS.wattlabPage);
  if (section) out.section = section;
  if (jobId) out.jobId = jobId;
  if (equipment) out.equipment = equipment;
  if (siteId) out.siteId = siteId;
  if (wattlabPage) out.wattlabPage = wattlabPage;
  return out;
}

export function buildSessionSearch(
  current: string,
  patch: Partial<SessionQuery>,
): string {
  const params = new URLSearchParams(
    current.startsWith("?") ? current.slice(1) : current,
  );
  const apply = (key: string, value: string | undefined) => {
    if (value === undefined) return;
    if (value === "") params.delete(key);
    else params.set(key, value);
  };
  apply(SESSION_KEYS.section, patch.section);
  apply(SESSION_KEYS.jobId, patch.jobId);
  apply(SESSION_KEYS.equipment, patch.equipment);
  apply(SESSION_KEYS.siteId, patch.siteId);
  apply(SESSION_KEYS.wattlabPage, patch.wattlabPage);
  const s = params.toString();
  return s ? `?${s}` : "";
}

/**
 * Navigate to a section path while keeping the locked site/equipment
 * (and job / wattlab page). Destination query wins for `section`.
 */
export function hrefWithSession(
  dest: string,
  currentSearch: string,
): string {
  const qIdx = dest.indexOf("?");
  const pathname = qIdx < 0 ? dest : dest.slice(0, qIdx);
  const destSearch = qIdx < 0 ? "" : dest.slice(qIdx);
  const cur = parseSessionSearch(currentSearch);
  const next = parseSessionSearch(destSearch);
  return `${pathname}${buildSessionSearch("", {
    siteId: next.siteId ?? cur.siteId,
    equipment: next.equipment ?? cur.equipment,
    jobId: next.jobId ?? cur.jobId,
    wattlabPage: next.wattlabPage ?? cur.wattlabPage,
    section: next.section,
  })}`;
}

/** Form draft only — never authoritative job/mapping state. */
export type FormDraftStore = Record<string, unknown>;

const DRAFT_PREFIX = "openfdd.formDraft.";

export function loadFormDraft(key: string): FormDraftStore | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_PREFIX + key);
    if (!raw) return null;
    return JSON.parse(raw) as FormDraftStore;
  } catch {
    return null;
  }
}

export function saveFormDraft(key: string, draft: FormDraftStore): void {
  sessionStorage.setItem(DRAFT_PREFIX + key, JSON.stringify(draft));
}

export function clearFormDraft(key: string): void {
  sessionStorage.removeItem(DRAFT_PREFIX + key);
}
