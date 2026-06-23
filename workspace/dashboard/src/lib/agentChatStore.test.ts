import { describe, expect, it } from "vitest";
import {
  appendPendingAssistant,
  appendUserMessage,
  buildChatHistoryPayload,
  deleteMessage,
  deleteMessageAndAfter,
  loadAgentChat,
  resolveAssistant,
  type AgentChatState,
} from "./agentChatStore";

function base(): AgentChatState {
  return loadAgentChat();
}

describe("agentChatStore", () => {
  it("buildChatHistoryPayload skips pending messages", () => {
    let s = appendUserMessage(base(), "hello");
    const pending = appendPendingAssistant(s);
    s = pending.state;
    expect(buildChatHistoryPayload(s.messages)).toEqual([{ role: "user", content: "hello" }]);
  });

  it("deleteMessage removes one row", () => {
    let s = appendUserMessage(base(), "a");
    const id = s.messages[0].id;
    s = deleteMessage(s, id);
    expect(s.messages).toHaveLength(0);
  });

  it("deleteMessageAndAfter truncates tail", () => {
    let s = appendUserMessage(base(), "one");
    s = appendUserMessage(s, "two");
    s = appendUserMessage(s, "three");
    const cutId = s.messages[1].id;
    s = deleteMessageAndAfter(s, cutId);
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0].content).toBe("one");
  });

  it("resolveAssistant marks done", () => {
    let s = appendUserMessage(base(), "hi");
    const pending = appendPendingAssistant(s);
    s = resolveAssistant(pending.state, pending.id, "yo", "", true, { durationMs: 100 });
    expect(s.messages[1].status).toBe("done");
    expect(s.messages[1].content).toBe("yo");
  });
});
