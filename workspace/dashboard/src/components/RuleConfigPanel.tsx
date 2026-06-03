type Props = {
  config: Record<string, string>;
  onChange: (config: Record<string, string>) => void;
  presets?: { key: string; label: string; defaultValue: string }[];
};

const DEFAULT_PRESETS = [
  { key: "high", label: "High threshold", defaultValue: "75" },
  { key: "low", label: "Low threshold", defaultValue: "55" },
  { key: "rolling_avg_minutes", label: "Rolling avg (min: 1, 5, 15)", defaultValue: "5" },
  { key: "flatline_minutes", label: "Flatline window (min)", defaultValue: "30" },
];

function sanitizeKey(raw: string): string {
  return raw.trim().replace(/\s+/g, "_").replace(/[^\w]/g, "");
}

export default function RuleConfigPanel({ config, onChange, presets = DEFAULT_PRESETS }: Props) {
  const entries = Object.entries(config);
  const rows = entries.length ? entries : [["", ""] as [string, string]];

  function updateKey(oldKey: string, newKey: string, value: string) {
    const next = { ...config };
    if (oldKey && oldKey !== newKey) delete next[oldKey];
    const k = sanitizeKey(newKey);
    if (k) next[k] = value;
    onChange(next);
  }

  function updateValue(key: string, value: string) {
    onChange({ ...config, [key]: value });
  }

  function removeKey(key: string) {
    const next = { ...config };
    delete next[key];
    onChange(next);
  }

  function addRow() {
    onChange({ ...config, "": "" });
  }

  function addPreset(key: string, defaultValue: string) {
    if (config[key] !== undefined) return;
    onChange({ ...config, [key]: defaultValue });
  }

  return (
    <div className="rule-config-panel panel">
      <div className="cfg-panel-head">
        <span className="cfg-panel-title">Parameters (cfg)</span>
        <span className="muted cfg-panel-hint">Passed to evaluate(row, cfg, …)</span>
        <div className="cfg-toolbar">
          <button type="button" className="secondary icon-btn" onClick={addRow} title="Add parameter">
            + Parameter
          </button>
          <select
            className="cfg-preset-select"
            defaultValue=""
            onChange={(e) => {
              const key = e.target.value;
              e.target.value = "";
              if (!key) return;
              const preset = presets.find((p) => p.key === key);
              addPreset(key, preset?.defaultValue || "");
            }}
          >
            <option value="">Add preset…</option>
            {presets.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label} ({p.key})
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="cfg-param-head">
        <span>Key</span>
        <span>Value</span>
        <span />
      </div>
      <div className="cfg-param-list">
        {rows.map(([key, value], idx) => (
          <div className="cfg-param-row" key={`${key}-${idx}`}>
            <input
              className="cfg-key"
              value={key}
              placeholder="high"
              onChange={(e) => updateKey(key, e.target.value, value)}
              onBlur={(e) => updateKey(key, sanitizeKey(e.target.value), value)}
            />
            <input
              className="cfg-val"
              value={value}
              placeholder="75"
              onChange={(e) => updateValue(sanitizeKey(key) || key, e.target.value)}
            />
            <button type="button" className="secondary icon-btn cfg-remove" onClick={() => removeKey(key)} title="Remove">
              −
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function configToRecord(cfg: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(cfg || {})) {
    if (k) out[k] = v == null ? "" : String(v);
  }
  return out;
}

export function configFromRecord(cfg: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(cfg)) {
    const key = sanitizeKey(k);
    if (!key) continue;
    const num = Number(v);
    out[key] = v.trim() !== "" && Number.isFinite(num) ? num : v;
  }
  return out;
}
