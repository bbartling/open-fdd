import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TenantSwitcher } from "./TenantSwitcher";

const memberships = [
  { id: "tenant_a", name: "Tenant A" },
  { id: "tenant_b", name: "Tenant B" },
];

describe("TenantSwitcher", () => {
  it("stays hidden when the user has one membership", () => {
    render(
      <TenantSwitcher
        tenants={[{ id: "tenant_a", name: "Tenant A" }]}
        activeTenantId="tenant_a"
        onSelect={() => undefined}
      />,
    );
    expect(screen.queryByTestId("app-tenant-select")).toBeNull();
  });

  it("lists memberships and reports a different tenant", () => {
    const onSelect = vi.fn();
    render(
      <TenantSwitcher
        tenants={memberships}
        activeTenantId="tenant_a"
        onSelect={onSelect}
      />,
    );
    const select = screen.getByTestId("app-tenant-select") as HTMLSelectElement;
    expect(screen.getByText("Tenant")).toBeTruthy();
    expect(select.value).toBe("tenant_a");
    const labels = [...select.options].map((opt) => opt.textContent);
    expect(labels).toEqual(["Tenant A", "Tenant B"]);
    fireEvent.change(select, { target: { value: "tenant_a" } });
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.change(select, { target: { value: "tenant_b" } });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("tenant_b");
  });
});
