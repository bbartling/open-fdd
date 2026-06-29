type Props = {
  sql: string;
  readOnly?: boolean;
  onChange?: (sql: string) => void;
  onInsert?: (snippet: string) => void;
  lineCount?: number;
};

export default function SqlFddQueryEditor({ sql, readOnly, onChange, lineCount }: Props) {
  const lines = Math.max(8, lineCount ?? sql.split("\n").length + 1);

  return (
    <div className="gf-sql-editor">
      <div className="gf-sql-editor__gutter" aria-hidden>
        {Array.from({ length: lines }, (_, i) => (
          <span key={i + 1}>{i + 1}</span>
        ))}
      </div>
      <textarea
        className="gf-sql-editor__input"
        value={sql}
        readOnly={readOnly}
        spellCheck={false}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder="SELECT timestamp, equipment_id, oa_t, … AS fault_raw FROM telemetry_pivot WHERE equipment_id = '…'"
        rows={lines}
      />
    </div>
  );
}
