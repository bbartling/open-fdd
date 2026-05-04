import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LEGACY_CHAT_STORAGE_KEY, SESSIONS_STORAGE_KEY } from "../lib/local-codex-sessions";
import { AiAgentChatPage } from "./AiAgentChatPage";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    desktopFetch: vi.fn(),
  };
});

import { desktopFetch } from "../lib/api";

const desktopFetchMock = vi.mocked(desktopFetch);

function renderChat() {
  return render(<AiAgentChatPage />);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const WORKDIR_KEY = "ofdd-local-codex-workdir";

beforeEach(() => {
  try {
    localStorage.removeItem(SESSIONS_STORAGE_KEY);
    localStorage.removeItem(LEGACY_CHAT_STORAGE_KEY);
    localStorage.removeItem(WORKDIR_KEY);
  } catch {
    /* ignore */
  }
  desktopFetchMock.mockReset();
  desktopFetchMock.mockImplementation(async (path: string) => {
    if (path === "/local-codex/diagnostics") {
      return {
        codex_path: null,
        npm_prefix: null,
        where_codex: [],
        login_status: null,
        hints: ["npm install -g @openai/codex"],
        exec_env: {
          ask_for_approval: "never",
          sandbox_mode: "danger-full-access",
          model_simple: "gpt-5.4-mini",
          model_complex_primary: "gpt-5.5",
          model_complex_fallback: "gpt-5.4",
          llm_route_classify: false,
        },
      };
    }
    throw new Error(`unexpected desktopFetch path: ${path}`);
  });
});

describe("AiAgentChatPage", () => {
  it("shows minimal header when signed in and no developer drawer", async () => {
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
          exec_env: {
          ask_for_approval: "never",
          sandbox_mode: "danger-full-access",
          model_simple: "gpt-5.4-mini",
          model_complex_primary: "gpt-5.5",
          model_complex_fallback: "gpt-5.4",
          llm_route_classify: false,
        },
        };
      }
      throw new Error(`unexpected path ${path}`);
    });

    const { container } = renderChat();
    expect(await screen.findByTestId("ofdd-agent-chat-heading")).toHaveTextContent("AI Agent");
    expect(screen.getByText("Signed in")).toBeInTheDocument();
    expect(screen.getByText(/OpenAI Codex on the bridge/i)).toBeInTheDocument();
    expect(screen.getByTestId("local-codex-model-chips")).toBeInTheDocument();
    expect(screen.getByText(/gpt-5.4-mini/)).toBeInTheDocument();
    expect(screen.getByText(/gpt-5.5/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Check sign-in/i })).toBeNull();
    expect(screen.queryByText(/First-time sign-in/i)).toBeNull();
    expect(screen.getByTestId("local-codex-thread")).toBeInTheDocument();
    expect(screen.getByTestId("local-codex-agents-rail")).toBeInTheDocument();
    expect(screen.getByTestId("local-codex-new-agent")).toBeInTheDocument();
    expect(screen.getByTestId("local-codex-sign-out")).toBeInTheDocument();
    expect(screen.getByLabelText("Codex working directory on the bridge")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Send$/i })).toBeInTheDocument();
    expect(screen.queryByTestId("plots-clean-metrics-panel")).toBeNull();
    expect(container.querySelector("[data-testid='ofdd-dev-details']")).toBeNull();
  });

  it("shows Install / Sign into OpenAI when CLI is missing", async () => {
    renderChat();
    expect(await screen.findByRole("button", { name: /Install agent CLI & sign in/i })).toBeInTheDocument();
  });

  it("restores thread and draft from localStorage after navigating away (remount)", async () => {
    localStorage.setItem(
      LEGACY_CHAT_STORAGE_KEY,
      JSON.stringify({
        v: 1,
        lines: [
          { role: "user", text: "stored question" },
          { role: "assistant", text: "stored answer" },
        ],
        draft: "partial reply",
      }),
    );
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
          exec_env: {
          ask_for_approval: "never",
          sandbox_mode: "danger-full-access",
          model_simple: "gpt-5.4-mini",
          model_complex_primary: "gpt-5.5",
          model_complex_fallback: "gpt-5.4",
          llm_route_classify: false,
        },
        };
      }
      throw new Error(`unexpected path ${path}`);
    });

    const { unmount } = renderChat();
    expect(await screen.findByText("stored question")).toBeInTheDocument();
    expect(screen.getByText("stored answer")).toBeInTheDocument();
    expect((screen.getByLabelText("Chat message") as HTMLTextAreaElement).value).toBe("partial reply");
    unmount();

    const { container: c2 } = renderChat();
    expect(await screen.findByText("stored question")).toBeInTheDocument();
    expect(c2).toBeTruthy();
  });

  it("renders backticks in assistant messages as inline code", async () => {
    localStorage.setItem(
      SESSIONS_STORAGE_KEY,
      JSON.stringify({
        v: 2,
        activeId: "s1",
        sessions: [
          {
            id: "s1",
            title: "Test",
            updatedAt: 1,
            draft: "",
            lines: [{ role: "assistant", text: "- `foo_bar`: `934`\n- `baz`: `1`" }],
          },
        ],
      }),
    );
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
          exec_env: {
            ask_for_approval: "never",
            sandbox_mode: "danger-full-access",
            model_simple: "gpt-5.4-mini",
            model_complex_primary: "gpt-5.5",
            model_complex_fallback: "gpt-5.4",
            llm_route_classify: false,
          },
        };
      }
      throw new Error(`unexpected path ${path}`);
    });
    renderChat();
    expect(await screen.findByText("foo_bar")).toBeInTheDocument();
    const codes = document.querySelectorAll(".local-codex-msg-code");
    expect(codes.length).toBeGreaterThanOrEqual(3);
    expect(Array.from(codes).some((c) => c.textContent === "foo_bar")).toBe(true);
  });

  it("shows thinking row while the bridge request is in flight", async () => {
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
          exec_env: {
          ask_for_approval: "never",
          sandbox_mode: "danger-full-access",
          model_simple: "gpt-5.4-mini",
          model_complex_primary: "gpt-5.5",
          model_complex_fallback: "gpt-5.4",
          llm_route_classify: false,
        },
        };
      }
      throw new Error(`unexpected path ${path}`);
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>(() => {
            /* never resolves */
          }),
      ),
    );

    renderChat();
    await screen.findByTestId("ofdd-agent-chat-heading");

    fireEvent.change(screen.getByLabelText("Codex working directory on the bridge"), {
      target: { value: "C:\\\\repo\\\\open-fdd" },
    });
    fireEvent.change(screen.getByLabelText("Chat message"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/i }));

    expect(await screen.findByTestId("ofdd-agent-thinking")).toBeInTheDocument();
    expect(screen.getByText(/Sending your message to the bridge/i)).toBeInTheDocument();
  });
});
