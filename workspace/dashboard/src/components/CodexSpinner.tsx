/** Animated spinner shown while Codex (or agent relay) is working. */
export default function CodexSpinner({ label = "Codex", size = 18 }: { label?: string; size?: number }) {
  return (
    <span className="codex-spinner" role="status" aria-live="polite" aria-label={`${label} working`}>
      <svg
        className="codex-spinner-icon"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle className="codex-spinner-track" cx="12" cy="12" r="9" fill="none" strokeWidth="2.5" />
        <path
          className="codex-spinner-arc"
          d="M12 3a9 9 0 0 1 9 9"
          fill="none"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span className="codex-spinner-label">{label}</span> : null}
    </span>
  );
}
