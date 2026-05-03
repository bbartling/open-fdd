import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  desktopFetchMock.mockReset();
  desktopFetchMock.mockImplementation(async (path: string) => {
    if (path === "/local-codex/diagnostics") {
      return {
        codex_path: null,
        npm_prefix: null,
        where_codex: [],
        login_status: null,
        hints: ["npm install -g @openai/codex"],
      };
    }
    if (path === "/assistant/readiness") {
      return {
        message_markdown: "",
        plots_quicklinks: [],
        suggested_actions: [],
        deep_links: {},
      };
    }
    throw new Error(`unexpected desktopFetch path: ${path}`);
  });
});

function expandDev(container: HTMLElement) {
  const details = container.querySelector("[data-testid='ofdd-dev-details']");
  if (!details) {
    throw new Error("missing dev details");
  }
  const summary = details.querySelector("summary");
  if (!summary) {
    throw new Error("missing dev summary");
  }
  fireEvent.click(summary);
}

function expandAdvanced(container: HTMLElement) {
  expandDev(container);
  const details = container.querySelector("[data-testid='ofdd-claw-advanced']");
  if (!details) {
    throw new Error("missing advanced details");
  }
  const summary = details.querySelector("summary");
  if (!summary) {
    throw new Error("missing summary");
  }
  fireEvent.click(summary);
}

function advancedPanel(container: HTMLElement) {
  const el = container.querySelector("[data-testid='ofdd-claw-advanced-panel']");
  if (!el) {
    throw new Error("advanced panel not mounted");
  }
  return within(el as HTMLElement);
}

describe("OpenClawChatPage", () => {
  it("renders minimal Codex auth + chat and collapsed developer section", async () => {
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/local-codex/diagnostics") {
        return {
          codex_path: "C:\\\\fake\\\\codex.cmd",
          npm_prefix: null,
          where_codex: [],
          login_status: { returncode: 0, stdout: "ok", stderr: "", logged_in: true },
          hints: [],
        };
      }
      throw new Error(`unexpected path ${path}`);
    });

    const { container } = render(<OpenClawChatPage />);
    expect(await screen.findByTestId("ofdd-ai-chat-heading")).toHaveTextContent("Codex");
    expect(screen.getByRole("button", { name: /Check sign-in/i })).toBeInTheDocument();
    expect(screen.getByTestId("local-codex-thread")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Send$/i })).toBeInTheDocument();
    const dev = container.querySelector("[data-testid='ofdd-dev-details'] > div");
    expect(dev).toHaveAttribute("aria-hidden", "true");
  });

  it("reveals advanced cron panel when developer and advanced sections are expanded", async () => {
    const { container } = render(<OpenClawChatPage />);
    await screen.findByTestId("ofdd-ai-chat-heading");
    expandAdvanced(container);
    const advancedHost = container.querySelector("[data-testid='ofdd-claw-advanced'] > div");
    expect(advancedHost).toHaveAttribute("aria-hidden", "false");
    const panel = advancedPanel(container);
    expect(panel.getByText("Operations (Cron / Memory / Skills)")).toBeInTheDocument();
  });

  it("updates cron command preview when draft changes inside advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    await screen.findByTestId("ofdd-ai-chat-heading");
    expandAdvanced(container);
    const panel = advancedPanel(container);
    const nameInput = (await panel.findByLabelText("Job name")) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Nightly Portfolio Sweep" } });
    const commandPreview = panel.getByLabelText("Cron add command") as HTMLTextAreaElement;
    expect(commandPreview.value).toContain("Nightly Portfolio Sweep");
  });

  it("switches to PowerShell mode inside advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    await screen.findByTestId("ofdd-ai-chat-heading");
    expandAdvanced(container);
    const panel = advancedPanel(container);
    fireEvent.click(await panel.findByRole("button", { name: "PowerShell" }));
    const memoryPreview = panel.getByLabelText("Memory cleanup commands") as HTMLTextAreaElement;
    expect(memoryPreview.value).toContain("Set-Content");
    expect(memoryPreview.value).not.toContain("truncate -s 0");
  });

  it("shows cron validation warning for malformed expression in advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    await screen.findByTestId("ofdd-ai-chat-heading");
    expandAdvanced(container);
    const panel = advancedPanel(container);
    const cronInput = (await panel.findByLabelText("Cron schedule")) as HTMLInputElement;
    fireEvent.change(cronInput, { target: { value: "* * *" } });
    expect(panel.getByText(/Needs attention/i)).toBeInTheDocument();
  });

  it("shows API mode controls when selected in advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    await screen.findByTestId("ofdd-ai-chat-heading");
    expandAdvanced(container);
    const panel = advancedPanel(container);
    fireEvent.click(await panel.findByRole("button", { name: "Create via API" }));
    expect(panel.getByLabelText("Endpoint preset")).toBeInTheDocument();
    expect(panel.getByLabelText("API endpoint path")).toBeInTheDocument();
    expect(panel.getByRole("button", { name: /Create This Job via API/i })).toBeInTheDocument();
    expect(panel.getByLabelText("API request preview (curl)")).toBeInTheDocument();
  });
});
