import type { DisplayFault } from "../../lib/displayFaults";

type Props = {
  fault: DisplayFault;
  onSelect: (fault: DisplayFault) => void;
};

export default function FaultCard({ fault, onSelect }: Props) {
  return (
    <button
      type="button"
      className={`bis-fault bis-fault-${fault.severity}`}
      onClick={() => onSelect(fault)}
    >
      <div className="bis-fault-head">
        <span className={`bis-severity-pill bis-sev-${fault.severity}`}>{fault.severityLabel}</span>
        <span className="bis-fault-eq">{fault.equipmentLabel}</span>
      </div>
      <div className="bis-fault-title">{fault.title}</div>
      {fault.detail ? <div className="bis-fault-desc">{fault.detail}</div> : null}
      {fault.meta.length ? (
        <div className="bis-fault-meta">
          {fault.meta.map((m) => (
            <span key={m.label}>
              <span className="bis-fault-meta-label">{m.label}</span>{" "}
              <strong>{m.value}</strong>
            </span>
          ))}
        </div>
      ) : null}
    </button>
  );
}
