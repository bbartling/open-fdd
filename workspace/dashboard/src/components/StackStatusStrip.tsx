import { useDashboardStream, type ServiceStatus } from "../lib/dashboardStream";

function StatusDot({
  status,
  label,
  title,
}: {
  status: ServiceStatus;
  label: string;
  title?: string;
}) {
  return (
    <span className={`status-pill status-${status}`} title={title ?? label}>
      <span className={`status-dot status-dot-${status}`} aria-hidden />
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
    <div className="stack-strip">
      {stack.services.map((svc) => {
        const optionalGray = svc.id === "ollama" && (svc.status === "gray" || svc.optional);
        const label =
          svc.id === "ollama" && svc.status === "yellow"
            ? svc.label
            : optionalGray
              ? "Ollama (off)"
              : svc.label;
        const title =
          typeof svc.detail === "string" ? svc.detail : JSON.stringify(svc.detail);
        return (
          <StatusDot
            key={svc.id}
            status={svc.status}
            label={label}
            title={title}
          />
        );
      })}
    </div>
  );
}
