import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OpenFddClawAdvancedPanel } from "./OpenFddClawAdvancedPanel";

function advancedPanel(container: HTMLElement) {
  const el = container.querySelector("[data-testid='ofdd-claw-advanced-panel']");
  if (!el) {
    throw new Error("advanced panel not mounted");
  }
  return within(el as HTMLElement);
}

describe("OpenFddClawAdvancedPanel", () => {
  it("renders operations section", () => {
    const { container } = render(<OpenFddClawAdvancedPanel />);
    const panel = advancedPanel(container);
    expect(panel.getByText("Operations (Cron / Memory / Skills)")).toBeInTheDocument();
  });

  it("updates cron command preview when draft changes", async () => {
    const { container } = render(<OpenFddClawAdvancedPanel />);
    const panel = advancedPanel(container);
    const nameInput = (await panel.findByLabelText("Job name")) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Nightly Portfolio Sweep" } });
    const commandPreview = panel.getByLabelText("Cron add command") as HTMLTextAreaElement;
    expect(commandPreview.value).toContain("Nightly Portfolio Sweep");
  });

  it("switches to PowerShell mode", async () => {
    const { container } = render(<OpenFddClawAdvancedPanel />);
    const panel = advancedPanel(container);
    fireEvent.click(await panel.findByRole("button", { name: "PowerShell" }));
    const memoryPreview = panel.getByLabelText("Memory cleanup commands") as HTMLTextAreaElement;
    expect(memoryPreview.value).toContain("Set-Content");
    expect(memoryPreview.value).not.toContain("truncate -s 0");
  });

  it("shows cron validation warning for malformed expression", async () => {
    const { container } = render(<OpenFddClawAdvancedPanel />);
    const panel = advancedPanel(container);
    const cronInput = (await panel.findByLabelText("Cron schedule")) as HTMLInputElement;
    fireEvent.change(cronInput, { target: { value: "* * *" } });
    expect(panel.getByText(/Needs attention/i)).toBeInTheDocument();
  });

  it("shows API mode controls when selected", async () => {
    const { container } = render(<OpenFddClawAdvancedPanel />);
    const panel = advancedPanel(container);
    fireEvent.click(await panel.findByRole("button", { name: "Create via API" }));
    expect(panel.getByLabelText("Endpoint preset")).toBeInTheDocument();
    expect(panel.getByLabelText("API endpoint path")).toBeInTheDocument();
    expect(panel.getByRole("button", { name: /Create This Job via API/i })).toBeInTheDocument();
    expect(panel.getByLabelText("API request preview (curl)")).toBeInTheDocument();
  });
});
