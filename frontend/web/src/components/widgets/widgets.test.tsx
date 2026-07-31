import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { Select } from "./Select";
import { Slider } from "./Slider";
import { Checkbox } from "./Checkbox";
import { ConfirmModal } from "./ConfirmModal";
import { Expander } from "./Expander";

describe("widget primitives", () => {
  it("Select fires onChange when value changes", () => {
    const onChange = vi.fn();
    render(
      <Select
        id="test-select"
        label="Pick one"
        value="a"
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ]}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Pick one"), {
      target: { value: "b" },
    });
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("Slider responds to arrow keys", () => {
    const onChange = vi.fn();
    render(
      <Slider
        id="test-slider"
        label="Level"
        value={50}
        min={0}
        max={100}
        step={5}
        onChange={onChange}
      />,
    );

    const slider = screen.getByLabelText("Level");
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith(55);

    onChange.mockClear();
    fireEvent.keyDown(slider, { key: "ArrowDown" });
    expect(onChange).toHaveBeenCalledWith(45);
  });

  it("Checkbox toggles checked state", () => {
    const onChange = vi.fn();
    render(
      <Checkbox
        id="test-checkbox"
        label="Accept terms"
        checked={false}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByLabelText("Accept terms"));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("ConfirmModal opens and confirms", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open modal
          </button>
          <ConfirmModal
            id="test-modal"
            open={open}
            title="Delete job?"
            message="This cannot be undone."
            onConfirm={() => {
              onConfirm();
              setOpen(false);
            }}
            onCancel={() => {
              onCancel();
              setOpen(false);
            }}
          />
        </>
      );
    }

    render(<Harness />);
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByText("Open modal"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Delete job?")).toBeTruthy();

    fireEvent.click(screen.getByTestId("test-modal-confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Expander toggles expanded content", () => {
    function Harness() {
      const [expanded, setExpanded] = useState(false);
      return (
        <Expander
          id="test-expander"
          label="Details"
          expanded={expanded}
          onChange={setExpanded}
        >
          <p>Hidden content</p>
        </Expander>
      );
    }

    render(<Harness />);
    expect(screen.queryByText("Hidden content")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Details/i }));
    expect(screen.getByText("Hidden content")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Details/i }));
    expect(screen.queryByText("Hidden content")).toBeNull();
  });
});
