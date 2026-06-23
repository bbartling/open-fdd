import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchSavedRules,
  patchRuleBinding,
  rulesBoundToTarget,
  unbindRuleFromTarget,
  notifyAssignmentsChanged,
  type BindTarget,
  type SavedRule,
} from "../lib/ruleBindings";
import { formatApiError } from "../lib/formatApiError";
import { formatRuleLabel } from "../lib/ruleDisplay";

export type RulePinTarget = {
  kind: "point";
  id: string;
  label: string;
};

type MenuState = RulePinTarget & { x: number; y: number };

type Props = {
  menu: MenuState | null;
  onClose: () => void;
  onStatus?: (msg: string) => void;
  onChanged?: () => void;
  rules?: SavedRule[];
};

export default function FddRulePinMenu({ menu, onClose, onStatus, onChanged, rules: rulesProp }: Props) {
  const [rules, setRules] = useState<SavedRule[]>(rulesProp ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (rulesProp) {
      setRules(rulesProp);
      return;
    }
    fetchSavedRules()
      .then(setRules)
      .catch((e) => setError(formatApiError(e)));
  }, [rulesProp, menu?.id]);

  const bindTarget = useMemo<BindTarget | null>(() => {
    if (!menu) return null;
    return { kind: "point", id: menu.id, label: menu.label };
  }, [menu]);

  const bound = useMemo(() => {
    if (!bindTarget) return [];
    return rulesBoundToTarget(rules, bindTarget);
  }, [rules, bindTarget]);

  const enabledRules = useMemo(() => rules.filter((r) => r.enabled !== false), [rules]);

  const applyRule = useCallback(
    async (rule: SavedRule) => {
      if (!menu) return;
      setBusy(true);
      setError("");
      try {
        const updated = await patchRuleBinding({
          rule_id: rule.id,
          op: "add",
          kind: "point",
          target_id: menu.id,
        });
        setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
        onStatus?.(`Pinned "${rule.name}" → ${menu.label}`);
        notifyAssignmentsChanged();
        onChanged?.();
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setBusy(false);
        onClose();
      }
    },
    [menu, onClose, onChanged, onStatus],
  );

  const removeRule = useCallback(
    async (rule: SavedRule) => {
      if (!bindTarget) return;
      setBusy(true);
      setError("");
      try {
        const updated = await unbindRuleFromTarget(rule, bindTarget);
        setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
        onStatus?.(`Removed "${rule.name}" from ${bindTarget.label}`);
        notifyAssignmentsChanged();
        onChanged?.();
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setBusy(false);
        onClose();
      }
    },
    [bindTarget, onClose, onChanged, onStatus],
  );

  if (!menu) return null;

  return (
    <>
      <button type="button" className="context-menu-backdrop" aria-label="Close menu" onClick={onClose} />
      <div
        className="context-menu fdd-pin-menu"
        style={{ left: menu.x, top: menu.y }}
        role="menu"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="dm-context-hint">Pin FDD rule — {menu.label}</p>
        {busy ? <p className="muted">Updating…</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {!enabledRules.length ? (
          <p className="dm-context-muted">No enabled rules. Create one in Rule Lab.</p>
        ) : (
          enabledRules.map((r) => (
            <button key={r.id} type="button" role="menuitem" className="context-menu-item" onClick={() => void applyRule(r)}>
              Pin: {formatRuleLabel(r.name)}
            </button>
          ))
        )}
        {bound.length > 0 ? (
          <>
            <div className="dm-context-sep" />
            <p className="dm-context-hint">Remove pin</p>
            {bound.map((r) => (
              <button
                key={`rm-${r.id}`}
                type="button"
                role="menuitem"
                className="context-menu-item danger"
                onClick={() => void removeRule(r)}
              >
                Unpin: {formatRuleLabel(r.name)}
              </button>
            ))}
          </>
        ) : null}
      </div>
    </>
  );
}
