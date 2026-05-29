import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type ServiceStatus = "green" | "yellow" | "red" | "gray";

type StackService = {
  id: string;
  label: string;
  status: ServiceStatus;
  configured: boolean;
  detail: string | Record<string, unknown>;
  url?: string;
};

type StackHealth = {
  ok: boolean;
  overall: ServiceStatus;
  services: StackService[];
  bacnet_bind?: string | null;
};

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
  const [stack, setStack] = useState<StackHealth | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      apiFetch<StackHealth>("/health/stack")
        .then((data) => {
          if (!cancelled) {
            setStack(data);
            setError("");
          }
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    };
    load();
    const id = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

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
      {stack.services.map((svc) => (
        <StatusDot
          key={svc.id}
          status={svc.status}
          label={svc.label}
          title={
            typeof svc.detail === "string"
              ? svc.detail
              : JSON.stringify(svc.detail)
          }
        />
      ))}
    </div>
  );
}
