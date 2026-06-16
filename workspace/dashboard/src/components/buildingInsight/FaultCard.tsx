import type { DisplayFault } from "../../lib/displayFaults";

type Props = {
  fault: DisplayFault;
  onSelect: (fault: DisplayFault) => void;
  canClear?: boolean;
  clearing?: boolean;
  onClear?: (fault: DisplayFault) => void;
};

export default function FaultCard({ fault, onSelect, canClear, clearing, onClear }: Props) {
  return (
    <div className={`bis-fault bis-fault-${fault.severity}`}>
      <button type="button" className="bis-fault-main" onClick={() => onSelect(fault)}>
        <div className="bis-fault-head">
          <span className={`bis-severity-pill bis-sev-${fault.severity}`}>{fault.severityLabel}</span>
          {fault.dataSource ? <span className="bis-source-badge">{fault.dataSource}</span> : null}
        </div>
        <div className="bis-fault-device">{fault.title}</div>
        <div className="bis-fault-title">{fault.symptom}</div>
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
      {canClear && onClear ? (
        <button
          type="button"
          className="bis-fault-clear"
          disabled={clearing}
          title="Clear alarm — stays cleared until the fault condition returns"
          onClick={(e) => {
            e.stopPropagation();
            onClear(fault);
          }}
        >
          {clearing ? "Clearing…" : "Clear"}
        </button>
      ) : null}
    </div>
  );
}
