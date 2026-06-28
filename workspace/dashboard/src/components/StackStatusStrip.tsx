import { Link } from "react-router-dom";
import { useDashboardStream, type ServiceStatus } from "../lib/dashboardStream";

function StatusDot({
  status,
  label,
  title,
  disabled,
  href,
}: {
  status: ServiceStatus;
  label: string;
  title?: string;
  disabled?: boolean;
  href?: string;
}) {
  const pillClass = disabled ? "status-disabled" : `status-${status}`;
  const pill = (
    <span className={`status-pill ${pillClass}`} title={title ?? label}>
      <span className={`status-dot status-dot-${disabled ? "gray" : status}`} aria-hidden />
      {label}
    </span>
  );
  if (href && !disabled) {
    return (
      <Link to={href} className="stack-strip-link">
        {pill}
      </Link>
    );
  }
  return pill;
}

export default function StackStatusStrip() {
  const { snapshot, error } = useDashboardStream();

  const stack = snapshot?.stack;

  if (error && !stack) {
    return (
      <div className="stack-strip">
        <StatusDot status="red" label="Stack" title={error} />
      </div>
    );
  }

  if (!stack) {
    return (
      <div className="stack-strip">
        <StatusDot status="gray" label="Checking stack…" />
      </div>
    );
  }

  return (
    <div className="stack-strip" aria-label="Stack health">
      <div className="stack-strip-label">Data plane</div>
      <div className="stack-strip-pills">
        {stack.services.map((svc) => {
          const off = svc.configured === false || svc.status === "gray";
          const detail =
            typeof svc.detail === "string" ? svc.detail : JSON.stringify(svc.detail);
          return (
            <StatusDot
              key={svc.id}
              status={off ? "gray" : svc.status}
              disabled={off}
              label={off ? `${svc.label} · off` : svc.label}
              title={off ? `${detail} (not an error — disabled in this profile)` : detail}
              href={svc.href}
            />
          );
        })}
      </div>
    </div>
  );
}
