import { memo, useMemo } from "react";

export type TenantOption = {
  id: string;
  name: string;
};

type TenantSwitcherProps = {
  tenants: readonly TenantOption[];
  activeTenantId: string;
  disabled?: boolean;
  onSelect: (tenantId: string) => void;
};

function TenantSwitcherInner({
  tenants,
  activeTenantId,
  disabled = false,
  onSelect,
}: TenantSwitcherProps) {
  const options = useMemo(() => {
    const seen = new Set<string>();
    const out: TenantOption[] = [];
    const push = (id: string, name: string) => {
      const trimmed = id.trim();
      if (!trimmed || seen.has(trimmed)) return;
      seen.add(trimmed);
      out.push({ id: trimmed, name: name.trim() || trimmed });
    };
    for (const tenant of tenants) push(tenant.id, tenant.name);
    if (activeTenantId.trim() && !seen.has(activeTenantId.trim())) {
      push(activeTenantId, activeTenantId);
    }
    return out;
  }, [tenants, activeTenantId]);

  if (options.length < 2) return null;

  return (
    <label className="app-sidebar__tenant-select">
      <span className="oracle-sidebar__label">Tenant</span>
      <select
        className="oracle-sidebar__control"
        data-testid="app-tenant-select"
        value={activeTenantId}
        disabled={disabled}
        onChange={(event) => {
          const next = event.target.value;
          if (!next || next === activeTenantId) return;
          onSelect(next);
        }}
      >
        {options.map((opt) => (
          <option key={opt.id} value={opt.id}>
            {opt.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export const TenantSwitcher = memo(TenantSwitcherInner);
