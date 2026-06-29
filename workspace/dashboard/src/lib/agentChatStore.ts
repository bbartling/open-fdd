export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  status: "done" | "pending" | "error";
  createdAt: string;
  completedAt?: string;
  durationMs?: number;
  evalCount?: number;
  tokensPerSec?: number;
};

export type AgentChatState = {
  messages: ChatMessage[];
  draft: string;
  model: string;
  thinkLevel: string;
  busy: boolean;
  pendingMessageId: string | null;
};

export type ChatHistoryTurn = { role: "user" | "assistant"; content: string };

const STORAGE_KEY = "ofdd-agent-chat-v1";

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function loadAgentChat(): AgentChatState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return {
        messages: [],
        draft: "",
        model: "",
        thinkLevel: "off",
        busy: false,
        pendingMessageId: null,
      };
    }
    const parsed = JSON.parse(raw) as Partial<AgentChatState>;
    return {
      messages: Array.isArray(parsed.messages) ? parsed.messages : [],
      draft: typeof parsed.draft === "string" ? parsed.draft : "",
      model: typeof parsed.model === "string" ? parsed.model : "",
      thinkLevel: typeof parsed.thinkLevel === "string" ? parsed.thinkLevel : "off",
      busy: false,
      pendingMessageId: null,
    };
  } catch {
    return {
      messages: [],
      draft: "",
      model: "",
      thinkLevel: "off",
      busy: false,
      pendingMessageId: null,
    };
  }
}

export function saveAgentChat(state: AgentChatState): void {
  const payload: AgentChatState = {
    ...state,
    busy: false,
    pendingMessageId: null,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function appendUserMessage(state: AgentChatState, text: string): AgentChatState {
  const msg: ChatMessage = {
    id: newId(),
    role: "user",
    content: text,
    status: "done",
    createdAt: new Date().toISOString(),
  };
  return { ...state, messages: [...state.messages, msg], draft: "" };
}

export function appendPendingAssistant(state: AgentChatState): { state: AgentChatState; id: string } {
  const id = newId();
  const msg: ChatMessage = {
    id,
    role: "assistant",
    content: "…",
    status: "pending",
    createdAt: new Date().toISOString(),
  };
  return {
    id,
    state: {
      ...state,
      messages: [...state.messages, msg],
      busy: true,
      pendingMessageId: id,
    },
  };
}

export type AssistantTiming = {
  durationMs?: number;
  evalCount?: number;
  tokensPerSec?: number;
};

export function resolveAssistant(
  state: AgentChatState,
  id: string,
  content: string,
  thinking: string,
  ok: boolean,
  timing?: AssistantTiming,
): AgentChatState {
  const completedAt = new Date().toISOString();
  return {
    ...state,
    busy: false,
    pendingMessageId: null,
    messages: state.messages.map((m) => {
      if (m.id !== id) return m;
      const started = Date.parse(m.createdAt);
      const fallbackMs = Number.isFinite(started) ? Date.now() - started : undefined;
      return {
        ...m,
        content,
        thinking,
        status: ok ? "done" : ("error" as const),
        completedAt,
        durationMs: timing?.durationMs ?? fallbackMs,
        evalCount: timing?.evalCount,
        tokensPerSec: timing?.tokensPerSec,
      };
    }),
  };
}

/** Completed turns only — for Ollama multi-turn (backend trims further). */
export function buildChatHistoryPayload(messages: ChatMessage[]): ChatHistoryTurn[] {
  return messages
    .filter((m) => m.status !== "pending" && m.content.trim() && m.content !== "…")
    .map((m) => ({ role: m.role, content: m.content.trim() }));
}

export function deleteMessage(state: AgentChatState, id: string): AgentChatState {
  if (state.pendingMessageId === id) {
    return { ...state, messages: state.messages.filter((m) => m.id !== id), busy: false, pendingMessageId: null };
  }
  return { ...state, messages: state.messages.filter((m) => m.id !== id) };
}

/** Delete this message and everything after it (useful for trimming context manually). */
export function deleteMessageAndAfter(state: AgentChatState, id: string): AgentChatState {
  const idx = state.messages.findIndex((m) => m.id === id);
  if (idx < 0) return state;
  const pendingRemoved = state.messages.slice(idx).some((m) => m.id === state.pendingMessageId);
  return {
    ...state,
    messages: state.messages.slice(0, idx),
    busy: pendingRemoved ? false : state.busy,
    pendingMessageId: pendingRemoved ? null : state.pendingMessageId,
  };
}

export const AGENT_CHAT_CLEAR_EVENT = "ofdd-agent-chat-clear";

export function clearAgentChat(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/** Clear persisted chat and notify open agent panels to reset UI state. */
export function notifyClearAgentChat(): void {
  clearAgentChat();
  window.dispatchEvent(new CustomEvent(AGENT_CHAT_CLEAR_EVENT));
}
