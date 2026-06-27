import type { Node } from "@xyflow/react";

type Props = {
  node: Node | null;
  onPatch: (nodeId: string, patch: { label?: string; config?: Record<string, unknown> }) => void;
};

export default function WiresheetPropertyPanel({ node, onPatch }: Props) {
  if (!node) {
    return (
      <aside className="wiresheet-props" aria-label="Property panel">
        <h3 className="wiresheet-panel-title">Properties</h3>
        <p className="muted">Select a node to edit name, tags, inputs, and validation.</p>
      </aside>
    );
  }

  const data = node.data as {
    label?: string;
    nodeType?: string;
    config?: Record<string, unknown>;
    validation?: { status?: string; message?: string };
  };

  return (
    <aside className="wiresheet-props" aria-label="Property panel">
      <h3 className="wiresheet-panel-title">Properties</h3>
      <label className="field">
        <span className="field-label">Name</span>
        <input
          value={data.label ?? ""}
          onChange={(e) => onPatch(node.id, { label: e.target.value })}
        />
      </label>
      <label className="field">
        <span className="field-label">Type</span>
        <input value={data.nodeType ?? ""} readOnly className="readonly-field" />
      </label>
      <label className="field">
        <span className="field-label">Description</span>
        <textarea
          rows={3}
          value={String(data.config?.description ?? "")}
          onChange={(e) =>
            onPatch(node.id, { config: { ...data.config, description: e.target.value } })
          }
        />
      </label>
      <div className="wiresheet-props__section">
        <h4>Validation</h4>
        <p className="muted">
          {data.validation?.status ?? "pending"}
          {data.validation?.message ? ` — ${data.validation.message}` : ""}
        </p>
      </div>
      <div className="wiresheet-props__section">
        <h4>Config (JSON)</h4>
        <pre className="wiresheet-props__json">{JSON.stringify(data.config ?? {}, null, 2)}</pre>
      </div>
    </aside>
  );
}
