import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";
import { useMemo } from "react";
import { useTheme } from "../contexts/theme-context";

const lightEditorTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#0f172a",
      color: "#e2e8f0",
    },
    ".cm-content": {
      caretColor: "#38bdf8",
      fontSize: "14px",
      lineHeight: "1.55",
    },
    ".cm-cursor, .cm-dropCursor": {
      borderLeftColor: "#38bdf8",
    },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "#1e3a5f !important",
    },
    ".cm-gutters": {
      backgroundColor: "#0b1220",
      color: "#64748b",
      borderRight: "1px solid #1e293b",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "#111827",
    },
    ".cm-activeLine": {
      backgroundColor: "#111827",
    },
    ".cm-keyword": { color: "#7dd3fc" },
    ".cm-string": { color: "#86efac" },
    ".cm-number": { color: "#fcd34d" },
    ".cm-comment": { color: "#64748b", fontStyle: "italic" },
  },
  { dark: false },
);

const darkSqlTheme = EditorView.theme(
  {
    ".cm-content": {
      fontSize: "14px",
      lineHeight: "1.55",
    },
  },
  { dark: true },
);

type Props = {
  value: string;
  onChange: (value: string) => void;
  height?: string;
  readOnly?: boolean;
};

export default function SqlCodeEditor({ value, onChange, height = "320px", readOnly }: Props) {
  const { theme } = useTheme();

  const extensions = useMemo(
    () => [
      sql(),
      theme === "dark" ? [oneDark, darkSqlTheme] : lightEditorTheme,
      EditorView.lineWrapping,
    ],
    [theme],
  );

  return (
    <div className="sql-code-editor-wrap">
      <CodeMirror
        value={value}
        height={height}
        theme={theme === "dark" ? "dark" : "light"}
        extensions={extensions}
        readOnly={readOnly}
        onChange={onChange}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          indentOnInput: true,
          bracketMatching: true,
        }}
      />
    </div>
  );
}
