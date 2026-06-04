type Props = {
  label: string;
  score: number;
  color: string;
  deltaLabel?: string;
};

const R = 38;
const C = 2 * Math.PI * R;

export default function HealthGauge({ label, score, color, deltaLabel }: Props) {
  const dash = (score / 100) * C;
  return (
    <div className="bis-gauge">
      <div className="bis-gauge-ring">
        <svg width="90" height="90" viewBox="0 0 90 90" aria-hidden>
          <circle cx="45" cy="45" r={R} strokeWidth="9" fill="none" className="bis-ring-bg" />
          <circle
            cx="45"
            cy="45"
            r={R}
            strokeWidth="9"
            fill="none"
            stroke={color}
            strokeDasharray={`${dash} ${C}`}
            strokeLinecap="round"
            transform="rotate(-90 45 45)"
          />
        </svg>
        <div className="bis-gauge-score" style={{ color }}>
          {score}
        </div>
      </div>
      <div className="bis-gauge-label">{label}</div>
      {deltaLabel ? <div className="bis-gauge-delta">{deltaLabel}</div> : null}
    </div>
  );
}
