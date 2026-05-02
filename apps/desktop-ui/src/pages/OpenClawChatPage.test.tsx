import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OpenClawChatPage } from "./OpenClawChatPage";

function expandAdvanced(container: HTMLElement) {
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
  it("renders chat-first layout with iframe and advanced section collapsed", () => {
    const { container } = render(<OpenClawChatPage />);
    expect(screen.getByText("Open-FDD Claw")).toBeInTheDocument();
    expect(screen.getByTitle("Open-FDD Claw UI")).toBeInTheDocument();
    expect(screen.getByText(/Sign in to OpenAI \(ChatGPT \/ Codex\)/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sign in to OpenAI \(Codex\)/i })).toBeInTheDocument();
    const advancedHost = container.querySelector("[data-testid='ofdd-claw-advanced'] > div");
    expect(advancedHost).toHaveAttribute("aria-hidden", "true");
  });

  it("reveals advanced cron panel when details is expanded", () => {
    const { container } = render(<OpenClawChatPage />);
    expandAdvanced(container);
    const advancedHost = container.querySelector("[data-testid='ofdd-claw-advanced'] > div");
    expect(advancedHost).toHaveAttribute("aria-hidden", "false");
    const panel = advancedPanel(container);
    expect(panel.getByText("Operations (Cron / Memory / Skills)")).toBeInTheDocument();
  });

  it("updates cron command preview when draft changes inside advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    expandAdvanced(container);
    const panel = advancedPanel(container);
    const nameInput = (await panel.findByLabelText("Job name")) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Nightly Portfolio Sweep" } });
    const commandPreview = panel.getByLabelText("Cron add command") as HTMLTextAreaElement;
    expect(commandPreview.value).toContain("Nightly Portfolio Sweep");
  });

  it("switches to PowerShell mode inside advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    expandAdvanced(container);
    const panel = advancedPanel(container);
    fireEvent.click(await panel.findByRole("button", { name: "PowerShell" }));
    const memoryPreview = panel.getByLabelText("Memory cleanup commands") as HTMLTextAreaElement;
    expect(memoryPreview.value).toContain("Set-Content");
    expect(memoryPreview.value).not.toContain("truncate -s 0");
  });

  it("shows cron validation warning for malformed expression in advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    expandAdvanced(container);
    const panel = advancedPanel(container);
    const cronInput = (await panel.findByLabelText("Cron schedule")) as HTMLInputElement;
    fireEvent.change(cronInput, { target: { value: "* * *" } });
    expect(panel.getByText(/Needs attention/i)).toBeInTheDocument();
  });

  it("shows API mode controls when selected in advanced", async () => {
    const { container } = render(<OpenClawChatPage />);
    expandAdvanced(container);
    const panel = advancedPanel(container);
    fireEvent.click(await panel.findByRole("button", { name: "Create via API" }));
    expect(panel.getByLabelText("Endpoint preset")).toBeInTheDocument();
    expect(panel.getByLabelText("API endpoint path")).toBeInTheDocument();
    expect(panel.getByRole("button", { name: /Create This Job via API/i })).toBeInTheDocument();
    expect(panel.getByLabelText("API request preview (curl)")).toBeInTheDocument();
  });
});
