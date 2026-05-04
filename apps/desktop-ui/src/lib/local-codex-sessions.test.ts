import { afterEach, describe, expect, it } from "vitest";
import {
  createEmptySession,
  loadCodexSessionBundle,
  MAX_AGENT_SESSIONS,
  pushNewAgentSession,
  SESSIONS_STORAGE_KEY,
  type CodexSessionBundle,
} from "./local-codex-sessions";

describe("pushNewAgentSession", () => {
  it("drops oldest session when exceeding MAX_AGENT_SESSIONS (FIFO)", () => {
    const oldest = createEmptySession("oldest");
    oldest.updatedAt = 1;
    const sessions = [oldest];
    for (let i = 1; i < MAX_AGENT_SESSIONS; i += 1) {
      const s = createEmptySession(`s${i}`);
      s.updatedAt = 1 + i;
      sessions.push(s);
    }
    const bundle: CodexSessionBundle = {
      activeId: sessions[sessions.length - 1].id,
      sessions,
    };
    const next = pushNewAgentSession(bundle);
    expect(next.sessions).toHaveLength(MAX_AGENT_SESSIONS);
    expect(next.sessions.some((s) => s.id === oldest.id)).toBe(false);
    expect(next.activeId).toBe(next.sessions[next.sessions.length - 1].id);
    expect(next.sessions[next.sessions.length - 1].title).toBe("New agent");
  });
});

describe("loadCodexSessionBundle", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("loads v2 bundle when activeId is not a string and falls back to first session id", () => {
    const s1 = { id: "a", title: "A", updatedAt: 1, lines: [], draft: "" };
    const s2 = { id: "b", title: "B", updatedAt: 2, lines: [], draft: "" };
    localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify({ v: 2, activeId: 999, sessions: [s1, s2] }));
    const b = loadCodexSessionBundle();
    expect(b.sessions.map((s) => s.id)).toEqual(["a", "b"]);
    expect(b.activeId).toBe("a");
  });

  it("uses last session when activeId string is stale", () => {
    const s1 = { id: "a", title: "A", updatedAt: 1, lines: [], draft: "" };
    const s2 = { id: "b", title: "B", updatedAt: 2, lines: [], draft: "" };
    localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify({ v: 2, activeId: "ghost", sessions: [s1, s2] }));
    const b = loadCodexSessionBundle();
    expect(b.activeId).toBe("b");
  });
});
