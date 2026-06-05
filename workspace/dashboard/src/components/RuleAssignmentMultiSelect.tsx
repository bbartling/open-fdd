import { useEffect, useRef, useState } from "react";
import { formatRuleLabel } from "../lib/ruleDisplay";
import { formatApiError } from "../lib/formatApiError";
import { patchRuleBinding, type SavedRule } from "../lib/ruleBindings";

type Props = {
  pointId: string;
  pointLabel: string;
  rules: SavedRule[];
  boundRuleIds: string[];
  disabled?: boolean;
  onChanged?: () => void;
  onStatus?: (msg: string) => void;
};

export default function RuleAssignmentMultiSelect({
  pointId,
  pointLabel,
  rules,
  boundRuleIds,
  disabled,
  onChanged,
  onStatus,
}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const enabledRules = rules.filter((r) => r.enabled !== false);
  const boundSet = new Set(boundRuleIds);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  async function toggle(rule: SavedRule) {
    if (busy || disabled) return;
    const isBound = boundSet.has(rule.id);
    setBusy(true);
    setError("");
    try {
      await patchRuleBinding({
        rule_id: rule.id,
        op: isBound ? "remove" : "add",
        kind: "point",
        target_id: pointId,
      });
      onStatus?.(
        isBound
          ? `Unpinned "${rule.name}" from ${pointLabel}`
          : `Pinned "${rule.name}" → ${pointLabel}`,
      );
      onChanged?.();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  const selected = enabledRules.filter((r) => boundSet.has(r.id));

  return (
    <div className="rule-assign-multi" ref={rootRef}>
      <button
        type="button"
        className="rule-assign-multi-trigger"
        disabled={disabled || busy || !enabledRules.length}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {selected.length ? (
          <span className="rule-assign-multi-badges">
            {selected.map((r) => (
              <span key={r.id} className="badge poll-badge" title={r.name}>
                {formatRuleLabel(r.name)}
              </span>
            ))}
          </span>
        ) : (
          <span className="muted">Select rules…</span>
        )}
        <span className="rule-assign-multi-chevron" aria-hidden>
          {open ? "▴" : "▾"}
        </span>
      </button>
      {open ? (
        <div className="rule-assign-multi-panel" role="listbox" aria-multiselectable>
          {enabledRules.map((r) => {
            const checked = boundSet.has(r.id);
            return (
              <label key={r.id} className="rule-assign-multi-option">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled || busy}
                  onChange={() => void toggle(r)}
                />
                <span>
                  <strong>{formatRuleLabel(r.name)}</strong>
                  {r.severity ? <span className="muted"> · {r.severity}</span> : null}
                </span>
              </label>
            );
          })}
        </div>
      ) : null}
      {error ? <span className="error" style={{ fontSize: "0.82rem" }}>{error}</span> : null}
    </div>
  );
}
