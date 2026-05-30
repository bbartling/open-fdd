export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  status: "done" | "pending" | "error";
  createdAt: string;
};

export type AgentChatState = {
  messages: ChatMessage[];
  draft: string;
  model: string;
  thinkLevel: string;
  busy: boolean;
  pendingMessageId: string | null;
};

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
        draft: "hello",
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

export function resolveAssistant(
  state: AgentChatState,
  id: string,
  content: string,
  thinking: string,
  ok: boolean,
): AgentChatState {
  return {
    ...state,
    busy: false,
    pendingMessageId: null,
    messages: state.messages.map((m) =>
      m.id === id
        ? { ...m, content, thinking, status: ok ? "done" : ("error" as const) }
        : m,
    ),
  };
}

export function clearAgentChat(): void {
  localStorage.removeItem(STORAGE_KEY);
}
