import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OpenClawChatPage } from "./OpenClawChatPage";

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
  return render(<OpenClawChatPage />);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CHAT_KEY = "ofdd-local-codex-chat-v1";

beforeEach(() => {
  try {
    localStorage.removeItem(CHAT_KEY);
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
        exec_env: { ask_for_approval: "never", sandbox_mode: "danger-full-access" },
      };
    }
    throw new Error(`unexpected desktopFetch path: ${path}`);
  });
});

describe("OpenClawChatPage", () => {
  it("shows minimal header when signed in and no developer drawer", async () => {
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
          exec_env: { ask_for_approval: "never", sandbox_mode: "danger-full-access" },
        };
      }
      throw new Error(`unexpected path ${path}`);
    });

    const { container } = renderChat();
    expect(await screen.findByTestId("ofdd-ai-chat-heading")).toHaveTextContent("Codex");
    expect(screen.getByText("Signed in with Codex.")).toBeInTheDocument();
    expect(screen.getByText(/danger-full-access/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Check sign-in/i })).toBeNull();
    expect(screen.queryByText(/First-time sign-in/i)).toBeNull();
    expect(screen.getByTestId("local-codex-thread")).toBeInTheDocument();
    expect(screen.getByLabelText("Codex working directory on the bridge")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Send$/i })).toBeInTheDocument();
    expect(screen.queryByTestId("plots-clean-metrics-panel")).toBeNull();
    expect(container.querySelector("[data-testid='ofdd-dev-details']")).toBeNull();
  });

  it("shows Install / Sign into OpenAI when CLI is missing", async () => {
    renderChat();
    expect(await screen.findByRole("button", { name: /Install Codex & sign into OpenAI/i })).toBeInTheDocument();
  });

  it("restores thread and draft from localStorage after navigating away (remount)", async () => {
    localStorage.setItem(
      CHAT_KEY,
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
          exec_env: { ask_for_approval: "never", sandbox_mode: "danger-full-access" },
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

  it("shows thinking row while the bridge request is in flight", async () => {
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
          exec_env: { ask_for_approval: "never", sandbox_mode: "danger-full-access" },
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
    await screen.findByTestId("ofdd-ai-chat-heading");

    fireEvent.change(screen.getByLabelText("Codex working directory on the bridge"), {
      target: { value: "C:\\\\repo\\\\open-fdd" },
    });
    fireEvent.change(screen.getByLabelText("Chat message"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/i }));

    expect(await screen.findByTestId("ofdd-codex-thinking")).toBeInTheDocument();
    expect(screen.getByText(/Sending your message to the bridge/i)).toBeInTheDocument();
  });
});
