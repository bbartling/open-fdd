import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OpenClawChatPage } from "./OpenClawChatPage";

describe("OpenClawChatPage", () => {
  it("renders embedded OpenClaw frame and operations sections", () => {
    render(<OpenClawChatPage />);
    expect(screen.getByText("OpenClaw Chat")).toBeInTheDocument();
    expect(screen.getByText("Operations (Cron / Memory / Skills)")).toBeInTheDocument();
    expect(screen.getByTitle("OpenClaw UI")).toBeInTheDocument();
  });

  it("updates cron command preview when draft changes", () => {
    render(<OpenClawChatPage />);
    const nameInput = screen.getAllByLabelText("Job name")[0] as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Nightly Portfolio Sweep" } });
    const commandPreview = screen.getAllByLabelText("Cron add command")[0] as HTMLTextAreaElement;
    expect(commandPreview.value).toContain("Nightly Portfolio Sweep");
  });

  it("switches to PowerShell mode and updates memory cleanup command", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "PowerShell" })[0]);
    const areas = screen.getAllByLabelText("Memory cleanup commands");
    const memoryPreview = areas[0] as HTMLTextAreaElement;
    expect(memoryPreview.value).toContain("Set-Content");
    expect(memoryPreview.value).not.toContain("truncate -s 0");
  });

  it("shows cron validation warning for malformed expression", () => {
    render(<OpenClawChatPage />);
    const cronInput = screen.getAllByLabelText("Cron schedule")[0] as HTMLInputElement;
    fireEvent.change(cronInput, { target: { value: "* * *" } });
    expect(screen.getByText(/Needs attention/i)).toBeInTheDocument();
  });

  it("shows API mode controls when selected", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Create via API" })[0]);
    expect(screen.getByLabelText("Endpoint preset")).toBeInTheDocument();
    expect(screen.getByLabelText("API endpoint path")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create This Job via API/i })).toBeInTheDocument();
    expect(screen.getByLabelText("API request preview (curl)")).toBeInTheDocument();
  });

  it("applies cron helper example button", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "@hourly" })[0]);
    const cronInput = screen.getAllByLabelText("Cron schedule")[0] as HTMLInputElement;
    expect(cronInput.value).toBe("@hourly");
  });
});

