import { useMemo } from "react";

export type DriverSelection = {
  protocol: "bacnet" | "modbus" | "json_api" | "haystack" | "root";
  title: string;
  subtitle?: string;
  fields: Array<{ label: string; value: string }>;
  badges?: string[];
  raw?: unknown;
};

type Props = {
  selection: DriverSelection | null;
};

export default function DriverDetailsPanel({ selection }: Props) {
  const rows = useMemo(() => selection?.fields ?? [], [selection]);

  if (!selection) {
    return (
      <section className="panel driver-details-panel empty">
        <h3 className="panel-title">Point details</h3>
        <p className="muted">Select a tree node to inspect status, values, polling, and mappings.</p>
      </section>
    );
  }

  return (
    <section className="panel driver-details-panel" aria-label="Driver node details">
      <header className="driver-details-head">
        <div>
          <span className="driver-details-protocol">{selection.protocol.toUpperCase()}</span>
          <h3 className="panel-title">{selection.title}</h3>
          {selection.subtitle ? <p className="muted">{selection.subtitle}</p> : null}
        </div>
        {selection.badges?.length ? (
          <div className="driver-details-badges">
            {selection.badges.map((b) => (
              <span className="badge" key={b}>
                {b}
              </span>
            ))}
          </div>
        ) : null}
      </header>
      <dl className="driver-details-grid">
        {rows.map((row) => (
          <div className="driver-details-row" key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value || "—"}</dd>
          </div>
        ))}
      </dl>
      {selection.raw ? (
        <details className="driver-details-raw">
          <summary>View raw JSON (advanced)</summary>
          <pre>{JSON.stringify(selection.raw, null, 2)}</pre>
        </details>
      ) : null}
    </section>
  );
}
