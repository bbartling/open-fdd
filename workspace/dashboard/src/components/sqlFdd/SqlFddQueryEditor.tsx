import { sql } from "@codemirror/lang-sql";
import CodeMirror from "@uiw/react-codemirror";
import { sqlEditorTheme, sqlSyntaxHighlight } from "../../lib/sqlEditorTheme";

type Props = {
  sql: string;
  readOnly?: boolean;
  onChange?: (sql: string) => void;
  onInsert?: (snippet: string) => void;
  lineCount?: number;
};

export default function SqlFddQueryEditor({ sql, readOnly, onChange, lineCount }: Props) {
  const minHeight = `${Math.max(200, (lineCount ?? sql.split("\n").length + 1) * 24)}px`;

  return (
    <div className="gf-sql-editor gf-sql-editor--codemirror">
      <CodeMirror
        value={sql}
        height={minHeight}
        readOnly={readOnly}
        basicSetup={{
          lineNumbers: true,
          foldGutter: false,
          highlightActiveLine: true,
          autocompletion: false,
        }}
        extensions={[sql(), sqlEditorTheme, sqlSyntaxHighlight]}
        onChange={(value) => onChange?.(value)}
        placeholder="SELECT timestamp, equipment_id, oa_t, … AS fault_raw FROM telemetry_pivot WHERE equipment_id = '…'"
      />
    </div>
  );
}
