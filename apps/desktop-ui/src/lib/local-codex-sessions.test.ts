import { describe, expect, it } from "vitest";
import {
  createEmptySession,
  MAX_AGENT_SESSIONS,
  pushNewAgentSession,
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
