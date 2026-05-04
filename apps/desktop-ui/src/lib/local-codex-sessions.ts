/** Built-in AI Agent chat: up to N saved threads in localStorage (browser-only; bridge uses local agent CLI). */

export type ChatLine = { role: "user" | "assistant"; text: string };

export type CodexAgentSession = {
  id: string;
  title: string;
  updatedAt: number;
  lines: ChatLine[];
  draft: string;
};

export type CodexSessionBundle = {
  activeId: string;
  sessions: CodexAgentSession[];
};

export const LEGACY_CHAT_STORAGE_KEY = "ofdd-local-codex-chat-v1";
export const SESSIONS_STORAGE_KEY = "ofdd-local-codex-sessions-v2";
export const MAX_AGENT_SESSIONS = 5;
export const MAX_STORED_CHAT_LINES = 120;
export const MAX_STORED_CHAT_CHARS = 320_000;

function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `s-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  }
}

export function trimStoredChatLines(lines: ChatLine[]): ChatLine[] {
  let out = lines.length > MAX_STORED_CHAT_LINES ? lines.slice(-MAX_STORED_CHAT_LINES) : lines;
  let chars = out.reduce((n, l) => n + l.text.length, 0);
  while (chars > MAX_STORED_CHAT_CHARS && out.length > 1) {
    out = out.slice(1);
    chars = out.reduce((n, l) => n + l.text.length, 0);
  }
  return out;
}

export function createEmptySession(title = "New agent"): CodexAgentSession {
  const now = Date.now();
  return { id: newId(), title, updatedAt: now, lines: [], draft: "" };
}

function parseLines(raw: unknown): ChatLine[] {
  if (!Array.isArray(raw)) return [];
  const lines: ChatLine[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const role = (item as { role?: unknown }).role;
    const text = (item as { text?: unknown }).text;
    if (role !== "user" && role !== "assistant") continue;
    if (typeof text !== "string") continue;
    lines.push({ role, text });
  }
  return trimStoredChatLines(lines);
}

/** Derive a short title from the first user line (Cursor-style thread label). */
export function titleFromFirstUserMessage(lines: ChatLine[], fallback: string): string {
  const first = lines.find((l) => l.role === "user");
  if (!first?.text?.trim()) return fallback;
  const t = first.text.trim().replace(/\s+/g, " ");
  return t.length > 44 ? `${t.slice(0, 44)}…` : t;
}

export function loadCodexSessionBundle(): CodexSessionBundle {
  try {
    const raw2 = localStorage.getItem(SESSIONS_STORAGE_KEY);
    if (raw2) {
      const parsed = JSON.parse(raw2) as {
        v?: number;
        activeId?: unknown;
        sessions?: unknown;
      };
      if (parsed.v === 2 && typeof parsed.activeId === "string" && Array.isArray(parsed.sessions)) {
        const sessions: CodexAgentSession[] = [];
        for (const s of parsed.sessions) {
          if (!s || typeof s !== "object") continue;
          const id = (s as { id?: unknown }).id;
          const title = (s as { title?: unknown }).title;
          const updatedAt = (s as { updatedAt?: unknown }).updatedAt;
          const draft = (s as { draft?: unknown }).draft;
          if (typeof id !== "string" || !id) continue;
          sessions.push({
            id,
            title: typeof title === "string" && title.trim() ? title.trim() : "New agent",
            updatedAt: typeof updatedAt === "number" && Number.isFinite(updatedAt) ? updatedAt : Date.now(),
            lines: parseLines((s as { lines?: unknown }).lines),
            draft: typeof draft === "string" ? draft : "",
          });
        }
        if (sessions.length === 0) {
          const s = createEmptySession();
          return { activeId: s.id, sessions: [s] };
        }
        const trimmed = sessions.slice(-MAX_AGENT_SESSIONS);
        let activeId = typeof parsed.activeId === "string" ? parsed.activeId : trimmed[0].id;
        if (!trimmed.some((x) => x.id === activeId)) {
          activeId = trimmed[trimmed.length - 1].id;
        }
        return { activeId, sessions: trimmed };
      }
    }
  } catch {
    /* ignore */
  }

  try {
    const raw1 = localStorage.getItem(LEGACY_CHAT_STORAGE_KEY);
    if (raw1) {
      const parsed = JSON.parse(raw1) as { v?: number; lines?: unknown; draft?: unknown };
      if (parsed.v === 1 && Array.isArray(parsed.lines)) {
        const lines = parseLines(parsed.lines);
        const draft = typeof parsed.draft === "string" ? parsed.draft : "";
        const s: CodexAgentSession = {
          id: newId(),
          title: titleFromFirstUserMessage(lines, "Previous chat"),
          updatedAt: Date.now(),
          lines,
          draft,
        };
        return { activeId: s.id, sessions: [s] };
      }
    }
  } catch {
    /* ignore */
  }

  const s = createEmptySession();
  return { activeId: s.id, sessions: [s] };
}

export function persistCodexSessionBundle(bundle: CodexSessionBundle): void {
  try {
    const trimmed = bundle.sessions.map((s) => ({
      ...s,
      lines: trimStoredChatLines(s.lines),
    }));
    const payload: CodexSessionBundle = {
      activeId: bundle.activeId,
      sessions: trimmed.slice(-MAX_AGENT_SESSIONS),
    };
    localStorage.setItem(
      SESSIONS_STORAGE_KEY,
      JSON.stringify({
        v: 2 as const,
        activeId: payload.activeId,
        sessions: payload.sessions,
      }),
    );
    localStorage.removeItem(LEGACY_CHAT_STORAGE_KEY);
  } catch {
    /* quota / private mode */
  }
}

/** Append a new session; keep at most MAX_AGENT_SESSIONS (drop oldest). */
export function pushNewAgentSession(bundle: CodexSessionBundle): CodexSessionBundle {
  const next = createEmptySession();
  let sessions = [...bundle.sessions, next];
  if (sessions.length > MAX_AGENT_SESSIONS) {
    sessions = sessions.slice(sessions.length - MAX_AGENT_SESSIONS);
  }
  return { activeId: next.id, sessions };
}

export function selectSession(bundle: CodexSessionBundle, id: string): CodexSessionBundle {
  if (!bundle.sessions.some((s) => s.id === id)) return bundle;
  return { ...bundle, activeId: id };
}

export function updateActiveSession(
  bundle: CodexSessionBundle,
  fn: (s: CodexAgentSession) => CodexAgentSession,
): CodexSessionBundle {
  const sessions = bundle.sessions.map((s) => (s.id === bundle.activeId ? fn(s) : s));
  return { ...bundle, sessions };
}

/** Update a session by id (for async completions after the user may have switched threads). */
export function updateSessionById(
  bundle: CodexSessionBundle,
  sessionId: string,
  fn: (s: CodexAgentSession) => CodexAgentSession,
): CodexSessionBundle {
  const sessions = bundle.sessions.map((s) => (s.id === sessionId ? fn(s) : s));
  return { ...bundle, sessions };
}
