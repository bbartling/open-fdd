import type { BuilderState, FddInput } from "./types";

type Props = {
  builder: BuilderState;
  fddInputs: FddInput[];
  onChange: (next: BuilderState) => void;
  disabled?: boolean;
};

export default function SqlFddVisualBuilder({ builder, fddInputs, onChange, disabled }: Props) {
  return (
    <div className="gf-visual-builder">
      <div className="gf-visual-builder__head">
        <h3 className="gf-section-title">Rule definition</h3>
        <p className="muted">Threshold rule on mapped FDD inputs — SQL updates live in the editor above.</p>
      </div>
      <div className="gf-form-grid">
        <label className="gf-field">
          <span className="gf-field__label">Rule name</span>
          <input
            disabled={disabled}
            value={builder.name}
            onChange={(e) => onChange({ ...builder, name: e.target.value })}
          />
        </label>
        <label className="gf-field">
          <span className="gf-field__label">FDD input</span>
          <select
            disabled={disabled}
            value={builder.input}
            onChange={(e) => onChange({ ...builder, input: e.target.value })}
          >
            {fddInputs.map((i) => (
              <option key={i.id} value={i.id}>
                {i.label} ({i.id})
              </option>
            ))}
          </select>
        </label>
        <label className="gf-field gf-field--narrow">
          <span className="gf-field__label">Operator</span>
          <select
            disabled={disabled}
            value={builder.operator}
            onChange={(e) => onChange({ ...builder, operator: e.target.value })}
          >
            {[">", "<", ">=", "<="].map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
        </label>
        <label className="gf-field gf-field--narrow">
          <span className="gf-field__label">Threshold</span>
          <input
            disabled={disabled}
            type="number"
            value={builder.value}
            onChange={(e) => onChange({ ...builder, value: Number(e.target.value) })}
          />
        </label>
        <label className="gf-field">
          <span className="gf-field__label">Fault code</span>
          <input
            disabled={disabled}
            value={builder.fault_code}
            onChange={(e) => onChange({ ...builder, fault_code: e.target.value })}
          />
        </label>
        <label className="gf-field gf-field--narrow">
          <span className="gf-field__label">Confirm (sec)</span>
          <input
            disabled={disabled}
            type="number"
            value={builder.confirmation_seconds}
            onChange={(e) => onChange({ ...builder, confirmation_seconds: Number(e.target.value) })}
          />
        </label>
      </div>
    </div>
  );
}
