type SpinnerProps = {
  label?: string;
  inline?: boolean;
};

export default function Spinner({ label, inline = true }: SpinnerProps) {
  return (
    <span className={`spinner-wrap${inline ? " spinner-inline" : ""}`} role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      {label ? <span className="spinner-label">{label}</span> : null}
    </span>
  );
}
