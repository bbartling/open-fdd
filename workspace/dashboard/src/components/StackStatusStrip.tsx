import { useDashboardStream, type ServiceStatus } from "../lib/dashboardStream";

function StatusDot({
  status,
  label,
  title,
  disabled,
}: {
  status: ServiceStatus;
  label: string;
  title?: string;
  disabled?: boolean;
}) {
  const pillClass = disabled ? "status-disabled" : `status-${status}`;
  return (
    <span className={`status-pill ${pillClass}`} title={title ?? label}>
      <span className={`status-dot status-dot-${disabled ? "gray" : status}`} aria-hidden />
      {label}
    </span>
  );
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
      {stack.services.map((svc) => {
        const off = svc.configured === false || svc.status === "gray";
        const detail =
          typeof svc.detail === "string"
            ? svc.detail
            : JSON.stringify(svc.detail);
        return (
          <StatusDot
            key={svc.id}
            status={off ? "gray" : svc.status}
            disabled={off}
            label={off ? `${svc.label} · off` : svc.label}
            title={off ? `${detail} (not an error — disabled in this profile)` : detail}
          />
        );
      })}
    </div>
  );
}
